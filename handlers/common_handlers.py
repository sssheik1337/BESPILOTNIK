from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    ErrorEvent,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    FSInputFile,
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pathlib import Path

from keyboards.inline import (
    ManualCategoryCallback,
    get_user_menu,
    get_admin_menu,
    get_manuals_menu,
    get_manual_files_menu,
    manual_category_cb,
)
from config import MAIN_ADMIN_IDS
from utils.storage import public_root
import logging
import traceback
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from utils.validators import validate_serial
from database.db import get_serial_history, get_manual_files
import asyncio

logger = logging.getLogger(__name__)

router = Router()


class UserState(StatesGroup):
    waiting_for_auto_delete = State()
    waiting_for_serial = State()
    menu = State()


START_IMAGE_NAMES = ("start1.jpg", "start2.jpg", "start3.jpg")


def get_start_media() -> list[InputMediaPhoto]:
    media: list[InputMediaPhoto] = []
    for image_name in START_IMAGE_NAMES:
        image_path = public_root() / image_name
        if not image_path.exists():
            logger.warning(
                "Стартовое изображение %s не найдено по пути %s",
                image_name,
                image_path,
            )
            continue
        media.append(InputMediaPhoto(media=FSInputFile(image_path)))
    return media


async def clear_serial_state(user_id, state: FSMContext, delay=12 * 3600):
    await asyncio.sleep(delay)
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        logger.info(f"Состояние серийного номера очищено для пользователя ID {user_id}")


def _scenario_selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛟 Запрос техподдержки", callback_data="request_support"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎓 Запись на обучение", callback_data="enroll_training"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📘 Руководство по настройке", callback_data="setup_manual"
                )
            ],
        ]
    )


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext, bot: Bot, **data):
    user_id = message.from_user.id
    username = message.from_user.username or "неизвестно"
    logger.info(f"Получена команда /start от пользователя @{username} (ID: {user_id})")
    logger.debug(f"Состояние FSM перед обработкой /start: {await state.get_data()}")
    db_pool = data.get("db_pool")
    if db_pool is None:
        logger.error("Database connection pool is missing in handler data")
        await message.answer("Ошибка подключения к базе данных. Попробуйте позже.")
        return
    is_admin = False
    is_employee = False
    async with db_pool.acquire() as conn:
        admin = await conn.fetchrow(
            "SELECT admin_id FROM admins WHERE admin_id = $1", user_id
        )
        logger.debug(f"Результат запроса admins для ID {user_id}: {admin}")
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True
        employee = await conn.fetchrow(
            "SELECT user_id, serial FROM users WHERE user_id = $1", user_id
        )
        logger.debug(f"Результат запроса users для ID {user_id}: {employee}")
        if employee:
            is_employee = True
    await state.clear()
    if is_admin:
        await message.answer(
            "Добро пожаловать, администратор!", reply_markup=get_admin_menu(user_id)
        )
        logger.debug(
            f"Пользователь @{username} (ID: {user_id}) определён как администратор"
        )
        logger.debug(f"Пользователь @{username} (ID: {user_id}) получил админское меню")
    elif is_employee:
        serial = employee["serial"]
        await state.update_data(serial=serial)
        await state.set_state(UserState.menu)
        await message.answer("Добро пожаловать!", reply_markup=get_user_menu())
        logger.debug(
            f"Пользователь @{username} (ID: {user_id}) определён как сотрудник"
        )
        logger.debug(
            f"Пользователь @{username} (ID: {user_id}) получил пользовательское меню"
        )
    else:
        await state.set_state(UserState.waiting_for_auto_delete)
        try:
            media = get_start_media()
            if media:
                await bot.send_media_group(chat_id=message.chat.id, media=media)
            await message.answer(
                "⚠️В целях безопасности включите автоматическое удаление сообщений через сутки в настройках Telegram.\n"
                "Инструкция в прикреплённых изображениях.⚠️",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ Я включил автоудаление",
                                callback_data="confirm_auto_delete",
                            )
                        ]
                    ]
                ),
            )
            logger.debug(
                f"Пользователь @{username} (ID: {user_id}) перенаправлен на запрос автоудаления"
            )
        except (TelegramBadRequest, TelegramForbiddenError, FileNotFoundError) as e:
            logger.error(
                f"Ошибка при запросе автоудаления для пользователя @{username} (ID: {user_id}): {str(e)}"
            )
            await message.answer("Ошибка. Попробуйте снова.")


@router.callback_query(F.data == "confirm_auto_delete")
async def confirm_auto_delete(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    logger.debug(
        f"Обработка confirm_auto_delete для пользователя @{username} (ID: {user_id})"
    )
    await callback.message.delete()
    await callback.message.answer(
        "Выберите действие:",
        reply_markup=_scenario_selection_keyboard(),
    )
    await state.set_state(None)
    logger.debug(
        f"Пользователь @{username} (ID: {user_id}) подтвердил автоудаление и запрошен выбор сценария"
    )
    await callback.answer()


@router.message(Command("getme"))
async def getme_command(message: Message):
    user = message.from_user
    username = user.username or "не указан"
    logger.debug(
        "Команда /getme от пользователя @%s (ID: %s)", user.username or "неизвестно", user.id
    )
    await message.answer(
        "Ваш Telegram ID: {id}\nUsername: {username}".format(
            id=user.id,
            username=f"@{username}" if user.username else username,
        )
    )


@router.callback_query(F.data == "request_support")
async def request_support(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    await callback.message.edit_text(
        "Введите серийный номер:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")],
            ]
        ),
    )
    await state.update_data(scenario="support")
    await state.set_state(UserState.waiting_for_serial)
    logger.debug(f"Пользователь @{username} (ID: {user_id}) выбрал запрос техподдержки")
    await callback.answer()


@router.callback_query(F.data == "setup_manual")
async def setup_manual(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    await callback.message.edit_text(
        "Введите серийный номер:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")],
            ]
        ),
    )
    await state.update_data(scenario="manual")
    await state.set_state(UserState.waiting_for_serial)
    logger.debug(
        f"Пользователь @{username} (ID: {user_id}) выбрал руководство по настройке"
    )
    await callback.answer()


@router.callback_query(F.data == "select_scenario")
async def select_scenario(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Выберите действие:", reply_markup=_scenario_selection_keyboard()
    )
    await state.set_state(None)
    logger.debug(
        f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) вернулся к выбору сценария"
    )
    await callback.answer()


@router.message(StateFilter(UserState.waiting_for_serial))
async def process_serial(message: Message, state: FSMContext, **data):
    user_id = message.from_user.id
    username = message.from_user.username or "неизвестно"
    logger.debug(
        f"Обработка серийного номера {message.text} от пользователя @{username} (ID: {user_id})"
    )
    db_pool = data["db_pool"]
    serial = message.text.strip()
    if not validate_serial(serial):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        )
        await message.answer(
            "Некорректный серийный номер. Введите заново:", reply_markup=keyboard
        )
        logger.warning(
            f"Некорректный серийный номер {serial} от @{username} (ID: {user_id})"
        )
        return
    serial_data, appeals = await get_serial_history(serial)
    if not serial_data:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        )
        await message.answer(
            f"Серийный номер {serial} не найден.", reply_markup=keyboard
        )
        logger.warning(f"Серийный номер {serial} не найден для @{username}")
        return
    await state.update_data(serial=serial)
    data_state = await state.get_data()
    scenario = data_state.get("scenario")
    await state.set_state(UserState.menu)
    try:
        await message.delete()
    except TelegramBadRequest as e:
        logger.error(
            f"Ошибка удаления сообщения от @{username} (ID: {user_id}): {str(e)}"
        )
    if scenario == "manual":
        await message.answer("Выберите руководство:", reply_markup=get_manuals_menu())
    else:
        await message.answer("Добро пожаловать!", reply_markup=get_user_menu())
    logger.info(
        f"Серийный номер {serial} сохранён в состоянии для пользователя ID {user_id}"
    )
    asyncio.create_task(clear_serial_state(user_id, state))


@router.callback_query(F.data == "main_menu")
async def return_to_main_menu(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **data
):
    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    logger.debug(
        f"Обработка возврата в главное меню для пользователя @{username} (ID: {user_id})"
    )
    db_pool = data["db_pool"]
    is_admin = False
    is_employee = False
    async with db_pool.acquire() as conn:
        admin = await conn.fetchrow(
            "SELECT admin_id FROM admins WHERE admin_id = $1", user_id
        )
        logger.debug(f"Результат запроса admins для ID {user_id}: {admin}")
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True
        employee = await conn.fetchrow(
            "SELECT user_id, serial FROM users WHERE user_id = $1", user_id
        )
        logger.debug(f"Результат запроса users для ID {user_id}: {employee}")
        if employee:
            is_employee = True
    try:
        await callback.message.delete()
    except TelegramBadRequest as e:
        logger.error(
            f"Ошибка удаления сообщения для пользователя @{username} (ID: {user_id}): {str(e)}"
        )
    if is_admin:
        await state.clear()
        await bot.send_message(
            chat_id=callback.message.chat.id,
            text="Добро пожаловать, администратор!",
            reply_markup=get_admin_menu(user_id),
        )
        logger.debug(
            f"Пользователь @{username} (ID: {user_id}) вернулся в админское меню"
        )
    elif is_employee:
        serial = employee["serial"]
        await state.update_data(serial=serial)
        await state.set_state(UserState.menu)
        await bot.send_message(
            chat_id=callback.message.chat.id,
            text="Добро пожаловать!",
            reply_markup=get_user_menu(),
        )
        logger.debug(
            f"Пользователь @{username} (ID: {user_id}) вернулся в пользовательское меню"
        )
    else:
        data_state = await state.get_data()
        serial = data_state.get("serial")
        scenario = data_state.get("scenario")
        if scenario:
            await state.set_state(None)
            await bot.send_message(
                chat_id=callback.message.chat.id,
                text="Выберите действие:",
                reply_markup=_scenario_selection_keyboard(),
            )
            logger.debug(
                f"Пользователь @{username} (ID: {user_id}) возвращён в главное меню выбора"
            )
            await callback.answer()
            return
        if serial:
            await state.set_state(UserState.menu)
            await bot.send_message(
                chat_id=callback.message.chat.id,
                text="Добро пожаловать!",
                reply_markup=get_user_menu(),
            )
            logger.debug(
                f"Пользователь @{username} (ID: {user_id}) вернулся в главное меню"
            )
        else:
            await state.set_state(UserState.waiting_for_auto_delete)
            try:
                media = get_start_media()
                if media:
                    await bot.send_media_group(
                        chat_id=callback.message.chat.id, media=media
                    )
                await bot.send_message(
                    chat_id=callback.message.chat.id,
                    text="⚠️В целях безопасности включите автоматическое удаление сообщений через сутки в настройках Telegram.\n"
                    "Инструкция в прикреплённых изображениях.⚠️",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Я ВКЛЮЧИЛ АВТОУДАЛЕНИЕ",
                                    callback_data="confirm_auto_delete",
                                )
                            ]
                        ]
                    ),
                )
                logger.debug(
                    f"Пользователь @{username} (ID: {user_id}) перенаправлен на запрос автоудаления"
                )
            except (TelegramBadRequest, TelegramForbiddenError, FileNotFoundError) as e:
                logger.error(
                    f"Ошибка возврата в главное меню для пользователя @{username} (ID: {user_id}): {str(e)}"
                )
                await bot.send_message(
                    chat_id=callback.message.chat.id, text="Ошибка. Попробуйте снова."
                )
    await callback.answer()


@router.callback_query(F.data == "manuals")
async def manuals_menu(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Выберите руководство:", reply_markup=get_manuals_menu()
    )
    await callback.answer()


@router.callback_query(
    manual_category_cb.filter((F.role == "user") & (F.action == "open"))
)
async def send_manual(callback: CallbackQuery, callback_data: dict):
    callback_data = ManualCategoryCallback.model_validate(callback_data)
    category = callback_data.category
    files = await get_manual_files(category)
    await callback.message.delete()
    if not files:
        await callback.message.answer(
            "Файлы отсутствуют.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="manuals")]]
            ),
        )
    else:
        await callback.message.answer(
            "Выберите файл руководства:",
            reply_markup=get_manual_files_menu(category, files, is_admin=False),
        )
    await callback.answer()


@router.errors()
async def error_handler(event: ErrorEvent):
    user = (
        event.update.message.from_user.username
        if event.update.message and event.update.message.from_user
        else "неизвестно"
    )
    exc_info = traceback.format_exc()
    logger.error(
        f"Ошибка: {event.exception} от пользователя @{user}\nПодробности: {exc_info}"
    )
    if event.update.message:
        await event.update.message.answer(
            "Произошла ошибка. Попробуйте снова или свяжитесь с поддержкой."
        )
