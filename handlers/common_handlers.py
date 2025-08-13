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
from database.db import get_serial_history
import asyncio

logger = logging.getLogger(__name__)

router = Router()

class UserState(StatesGroup):
    waiting_for_auto_delete = State()
    waiting_for_serial = State()
    menu = State()

async def clear_serial_state(user_id, state: FSMContext, delay=12*3600):  # 12 часов
    await asyncio.sleep(delay)
    current_state = await state.get_state()
    if current_state:
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
    is_employee = False
    async with db_pool.acquire() as conn:
        admin = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
        logger.debug(f"Результат запроса admins для ID {user_id}: {admin}")
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True
        employee = await conn.fetchrow("SELECT user_id, serial FROM users WHERE user_id = $1", user_id)
        logger.debug(f"Результат запроса users для ID {user_id}: {employee}")
        if employee:
            is_employee = True

    if is_admin:
        logger.debug(f"Пользователь @{username} (ID: {user_id}) определён как администратор")
        await message.answer("Добро пожаловать, администратор!", reply_markup=get_admin_menu(user_id))
        logger.debug(f"Пользователь @{username} (ID: {user_id}) получил админское меню")
        await state.clear()
    elif is_employee:
        logger.debug(f"Пользователь @{username} (ID: {user_id}) определён как сотрудник")
        serial_data = await conn.fetchrow("SELECT serial FROM users WHERE user_id = $1", user_id)
        await state.update_data(serial=serial_data["serial"])
        await state.set_state(UserState.menu)
        await message.answer("Добро пожаловать!", reply_markup=get_user_menu())
        logger.debug(f"Пользователь @{username} (ID: {user_id}) получил пользовательское меню")
    else:
        logger.debug(f"Пользователь @{username} (ID: {user_id}) не администратор и не сотрудник, установка состояния waiting_for_auto_delete")
        await state.set_state(UserState.waiting_for_auto_delete)
        try:
            media = [
                InputMediaPhoto(media=FSInputFile("/data/start1.jpg")),
                InputMediaPhoto(media=FSInputFile("/data/start2.jpg")),
                InputMediaPhoto(media=FSInputFile("/data/start3.jpg"))
            ]
            logger.debug(f"Отправка приветственного сообщения для пользователя @{username} (ID: {user_id})")
            await message.answer_media_group(media=media)
            await message.answer(
                "⚠️В целях безопасности включите автоматическое удаление сообщений через сутки в настройках Telegram.\n"
                "Инструкция в прикреплённых изображениях.⚠️",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Я ВКЛЮЧИЛ АВТОУДАЛЕНИЕ", callback_data="confirm_auto_delete")]
                ])
            )
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
    await callback.message.answer("Введите серийный номер:")
    logger.debug(f"Пользователь @{username} (ID: {user_id}) подтвердил автоудаление и запрошен серийный номер")
    await callback.answer()
    asyncio.create_task(clear_serial_state(user_id, state))  # 12 часов (по умолчанию)

@router.message(StateFilter(UserState.waiting_for_serial))
async def process_serial(message: Message, state: FSMContext, bot: Bot, **data):
    user_id = message.from_user.id
    username = message.from_user.username or "неизвестно"
    serial = message.text.strip()
    logger.debug(f"Обработка серийного номера {serial} от пользователя @{username} (ID: {user_id})")

    # Валидация формата серийного номера
    if not validate_serial(serial):
        await message.answer("Неверный формат серийного номера. Он должен содержать от 6 до 20 букв и цифр. Попробуйте снова:")
        logger.warning(f"Неверный формат серийного номера {serial} от пользователя @{username}")
        try:
            await message.delete()
        except TelegramBadRequest as e:
            logger.error(f"Ошибка удаления сообщения с серийным номером для пользователя @{username} (ID: {user_id}): {str(e)}")
        return

    # Проверка существования серийного номера в базе
    serial_data, _ = await get_serial_history(serial)
    if not serial_data:
        await message.answer("Серийный номер не найден в базе. Пожалуйста, введите существующий серийный номер:")
        logger.warning(f"Серийный номер {serial} не найден в базе для пользователя @{username}")
        try:
            await message.delete()
        except TelegramBadRequest as e:
            logger.error(f"Ошибка удаления сообщения с серийным номером для пользователя @{username} (ID: {user_id}): {str(e)}")
        return

    # Успешная валидация и проверка
    await state.update_data(serial=serial)
    await state.set_state(UserState.menu)
    await message.answer("Добро пожаловать!", reply_markup=get_user_menu())
    logger.info(f"Серийный номер {serial} сохранён в состоянии для пользователя ID {user_id}")
    asyncio.create_task(clear_serial_state(user_id, state))  # 12 часов (по умолчанию)
    try:
        await message.delete()
    except TelegramBadRequest as e:
        logger.error(f"Ошибка удаления сообщения с серийным номером для пользователя @{username} (ID: {user_id}): {str(e)}")

@router.callback_query(F.data == "main_menu")
async def return_to_main_menu(callback: CallbackQuery, state: FSMContext, bot: Bot, **data):
    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    logger.debug(f"Обработка возврата в главное меню для пользователя @{username} (ID: {user_id})")
    db_pool = data["db_pool"]
    is_admin = False
    is_employee = False
    async with db_pool.acquire() as conn:
        admin = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
        logger.debug(f"Результат запроса admins для ID {user_id}: {admin}")
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True
        employee = await conn.fetchrow("SELECT user_id, serial FROM users WHERE user_id = $1", user_id)
        logger.debug(f"Результат запроса users для ID {user_id}: {employee}")
        if employee:
            is_employee = True

    try:
        await callback.message.delete()  # Удаляем исходное сообщение
    except TelegramBadRequest as e:
        logger.error(f"Ошибка удаления сообщения для пользователя @{username} (ID: {user_id}): {str(e)}")

    if is_admin:
        await state.clear()
        await bot.send_message(
            chat_id=callback.message.chat.id,
            text="Добро пожаловать, администратор!",
            reply_markup=get_admin_menu(user_id)
        )
        logger.debug(f"Пользователь @{username} (ID: {user_id}) вернулся в админское меню")
    elif is_employee:
        serial = employee["serial"]
        await state.update_data(serial=serial)
        await state.set_state(UserState.menu)
        await bot.send_message(
            chat_id=callback.message.chat.id,
            text="Добро пожаловать!",
            reply_markup=get_user_menu()
        )
        logger.debug(f"Пользователь @{username} (ID: {user_id}) вернулся в пользовательское меню")
    else:
        data_state = await state.get_data()
        serial = data_state.get("serial")
        if serial:
            await state.set_state(UserState.menu)
            await bot.send_message(
                chat_id=callback.message.chat.id,
                text="Добро пожаловать!",
                reply_markup=get_user_menu()
            )
            logger.debug(f"Пользователь @{username} (ID: {user_id}) вернулся в главное меню")
        else:
            await state.set_state(UserState.waiting_for_auto_delete)
            try:
                media = [
                    InputMediaPhoto(media=FSInputFile("/data/start1.jpg")),
                    InputMediaPhoto(media=FSInputFile("/data/start2.jpg")),
                    InputMediaPhoto(media=FSInputFile("/data/start3.jpg"))
                ]
                await bot.send_media_group(chat_id=callback.message.chat.id, media=media)
                await bot.send_message(
                    chat_id=callback.message.chat.id,
                    text="⚠️В целях безопасности включите автоматическое удаление сообщений через сутки в настройках Telegram.\n"
                         "Инструкция в прикреплённых изображениях.⚠️",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Я ВКЛЮЧИЛ АВТОУДАЛЕНИЕ", callback_data="confirm_auto_delete")]
                    ])
                )
                logger.debug(f"Пользователь @{username} (ID: {user_id}) перенаправлен на запрос автоудаления")
            except (TelegramBadRequest, TelegramForbiddenError, FileNotFoundError) as e:
                logger.error(f"Ошибка возврата в главное меню для пользователя @{username} (ID: {user_id}): {str(e)}")
                await bot.send_message(
                    chat_id=callback.message.chat.id,
                    text="Ошибка. Попробуйте снова."
                )
    await callback.answer()

@router.errors()
async def error_handler(event: ErrorEvent):
    user = event.update.message.from_user.username if event.update.message and event.update.message.from_user else "неизвестно"
    exc_info = traceback.format_exc()
    logger.error(f"Ошибка: {event.exception} от пользователя @{user}\nПодробности: {exc_info}")
    if event.update.message:
        await event.update.message.answer("Произошла ошибка. Попробуйте снова или свяжитесь с поддержкой.")