from aiogram import Router, F, Bot
from aiogram.types import Message, ErrorEvent, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, FSInputFile
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from keyboards.inline import get_user_menu, get_admin_menu
from config import MAIN_ADMIN_IDS
import logging
import traceback
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from utils.validators import validate_serial
import asyncio

logger = logging.getLogger(__name__)

router = Router()

class UserState(StatesGroup):
    waiting_for_auto_delete = State()
    waiting_for_serial = State()
    menu = State()

async def clear_serial_state(user_id, bot, delay=12*3600):  # 12 часов
    await asyncio.sleep(delay)
    async with bot.dispatcher.storage.get_state(user_id=user_id, chat_id=user_id) as state:
        if state:
            await state.clear()
            logger.info(f"Состояние серийного номера очищено для пользователя ID {user_id}")

@router.message(Command(commands=["start"]))
async def start_command(message: Message, state: FSMContext, bot: Bot, **data):
    user_id = message.from_user.id
    username = message.from_user.username or "неизвестно"
    logger.info(f"Получена команда /start от пользователя @{username} (ID: {user_id})")
    logger.debug(f"Состояние FSM перед обработкой /start: {await state.get_data()}")
    db_pool = data["db_pool"]
    is_admin = False
    async with db_pool.acquire() as conn:
        admin = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
        logger.debug(f"Результат запроса admins для ID {user_id}: {admin}")
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True

    if is_admin:
        logger.debug(f"Пользователь @{username} (ID: {user_id}) определён как администратор")
        await message.answer("Добро пожаловать, администратор!", reply_markup=get_admin_menu(user_id))
        logger.debug(f"Пользователь @{username} (ID: {user_id}) получил админское меню")
        await state.clear()
    else:
        logger.debug(f"Пользователь @{username} (ID: {user_id}) не администратор, установка состояния waiting_for_auto_delete")
        await state.set_state(UserState.waiting_for_auto_delete)
        try:
            media = [
                InputMediaPhoto(media=FSInputFile("/data/start1.jpg")),
                InputMediaPhoto(media=FSInputFile("/data/start2.jpg")),
                InputMediaPhoto(media=FSInputFile("/data/start3.jpg"))
            ]
            logger.debug(f"Отправка приветственного сообщения для пользователя @{username} (ID: {user_id})")
            await message.answer(
                "Для безопасности включите автоматическое удаление сообщений через сутки в настройках Telegram.\n"
                "Инструкция в прикреплённых изображениях.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Я ВКЛЮЧИЛ АВТОУДАЛЕНИЕ", callback_data="confirm_auto_delete")]
                ])
            )
            await message.answer_media_group(media=media)
            logger.debug(f"Пользователь @{username} (ID: {user_id}) получил запрос на автоудаление")
        except (TelegramBadRequest, TelegramForbiddenError, FileNotFoundError) as e:
            logger.error(f"Ошибка отправки приветственного сообщения для пользователя @{username} (ID: {user_id}): {str(e)}")
            await message.answer("Ошибка загрузки инструкции. Убедитесь, что файлы инструкции доступны, и попробуйте снова.")

@router.callback_query(F.data == "confirm_auto_delete")
async def confirm_auto_delete(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    logger.debug(f"Обработка confirm_auto_delete для пользователя @{username} (ID: {user_id})")
    await state.set_state(UserState.waiting_for_serial)
    try:
        await callback.message.delete()
    except TelegramBadRequest as e:
        logger.error(f"Ошибка удаления сообщения для пользователя @{username} (ID: {user_id}): {str(e)}")
    await callback.message.answer("Введите серийный номер:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ]))
    logger.debug(f"Пользователь @{username} (ID: {user_id}) подтвердил автоудаление и запрошен серийный номер")
    await callback.answer()
    asyncio.create_task(clear_serial_state(user_id, bot, delay=60))  # 60 секунд для теста

@router.message(StateFilter(UserState.waiting_for_serial))
async def process_serial(message: Message, state: FSMContext, bot: Bot, **data):
    user_id = message.from_user.id
    username = message.from_user.username or "неизвестно"
    serial = message.text.strip()
    logger.debug(f"Обработка серийного номера {serial} от пользователя @{username} (ID: {user_id})")
    if not validate_serial(serial):
        await message.answer("Неверный формат серийного номера. Попробуйте снова:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Неверный серийный номер {serial} от пользователя @{username}")
        return
    await state.update_data(serial=serial)
    await state.set_state(UserState.menu)
    await message.answer("Добро пожаловать!", reply_markup=get_user_menu())
    logger.info(f"Серийный номер {serial} сохранён в состоянии для пользователя ID {user_id}")
    asyncio.create_task(clear_serial_state(user_id, bot, delay=60))  # 60 секунд для теста

@router.errors()
async def error_handler(event: ErrorEvent):
    user = event.update.message.from_user.username if event.update.message and event.update.message.from_user else "неизвестно"
    exc_info = traceback.format_exc()
    logger.error(f"Ошибка: {event.exception} от пользователя @{user}\nПодробности: {exc_info}")
    if event.update.message:
        await event.update.message.answer("Произошла ошибка. Попробуйте снова или свяжитесь с поддержкой.")