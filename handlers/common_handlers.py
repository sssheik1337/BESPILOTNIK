from aiogram import Router, F
from aiogram.types import Message, ErrorEvent
from aiogram.filters import Command
from keyboards.inline import get_user_menu, get_admin_menu
from config import MAIN_ADMIN_IDS
import logging
import traceback

logger = logging.getLogger(__name__)

router = Router()

@router.message(Command(commands=["start"]))
async def start_command(message: Message, **data):
    logger.info(f"Получена команда /start от пользователя @{message.from_user.username} (ID: {message.from_user.id})")
    user_id = message.from_user.id
    is_admin = False
    db_pool = data["db_pool"]
    async with db_pool.acquire() as conn:
        admin = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
        logger.debug(f"Результат запроса admins для ID {user_id}: {admin}")
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True

    if is_admin:
        await message.answer("Добро пожаловать, администратор!", reply_markup=get_admin_menu(user_id))
        logger.debug(f"Пользователь @{message.from_user.username} (ID: {user_id}) получил админское меню")
    else:
        await message.answer("Добро пожаловать!", reply_markup=get_user_menu())
        logger.debug(f"Пользователь @{message.from_user.username} (ID: {user_id}) получил пользовательское меню")

@router.errors()
async def error_handler(event: ErrorEvent):
    user = event.update.message.from_user.username if event.update.message and event.update.message.from_user else "неизвестно"
    exc_info = traceback.format_exc()
    logger.error(f"Ошибка: {event.exception} от пользователя @{user}\nПодробности: {exc_info}")
    if event.update.message:
        await event.update.message.answer("Произошла ошибка. Попробуйте снова или свяжитесь с поддержкой.")