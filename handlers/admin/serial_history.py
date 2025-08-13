from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from database.db import get_serial_history
from utils.validators import validate_serial
from config import MAIN_ADMIN_IDS
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = Router()

class AdminResponse(StatesGroup):
    serial = State()

async def show_appeal_page(message: Message, state: FSMContext, history: list, page: int, serial_data: dict):
    if not history:  # Проверяем, пустой ли список обращений
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer(f"Обращений по серийному номеру {serial_data.get('serial')} не найдено.", reply_markup=keyboard)
        logger.info(f"Нет обращений для серийного номера {serial_data.get('serial')} от @{message.from_user.username}")
        return
    appeal = history[page]
    response = (f"Заявка №{appeal['appeal_id']}:\n"
                f"Серийный номер: {appeal['serial']}\n"
                f"Статус: {appeal['status']}\n"
                f"Описание: {appeal['description']}\n"
                f"Дата создания: {appeal['created_time']}\n"
                f"Ответ: {appeal['response'] or 'Нет ответа'}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    if page > 0:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"serial_history_page_{page-1}")])
    if page + 1 < len(history):
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="Следующая ➡️", callback_data=f"serial_history_page_{page+1}")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    await message.answer(response, reply_markup=keyboard)
    logger.debug(f"Показана страница {page} истории серийного номера {serial_data.get('serial')} для @{message.from_user.username}")

@router.callback_query(F.data == "serial_history")
async def serial_history_prompt(callback: CallbackQuery, state: FSMContext, **data):
    user_id = callback.from_user.id
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    async with db_pool.acquire() as conn:
        is_employee = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
    if user_id not in MAIN_ADMIN_IDS and not is_employee:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка доступа к истории серийника от неадминистратора @{callback.from_user.username} (ID: {user_id})")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите серийный номер для просмотра истории:", reply_markup=keyboard)
    await state.set_state(AdminResponse.serial)
    logger.debug(f"Администратор @{callback.from_user.username} (ID: {user_id}) запросил историю по серийнику")

@router.message(StateFilter(AdminResponse.serial))
async def process_serial_history(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    serial = message.text.strip()
    if not validate_serial(serial):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Некорректный серийный номер. Введите заново:", reply_markup=keyboard)
        logger.warning(f"Некорректный серийный номер {serial} от @{message.from_user.username} (ID: {message.from_user.id})")
        return
    serial_data, appeals = await get_serial_history(serial)
    if not serial_data:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer(f"Серийный номер {serial} не найден.", reply_markup=keyboard)
        logger.warning(f"Серийный номер {serial} не найден для @{message.from_user.username}")
        return
    await state.update_data(serial=serial, history=appeals, serial_data=serial_data)
    try:
        await message.delete()
    except TelegramBadRequest as e:
        logger.error(f"Ошибка удаления сообщения от @{message.from_user.username} (ID: {message.from_user.id}): {str(e)}")
    await show_appeal_page(message, state, appeals, 0, serial_data)
    await state.update_data(page=0)
    logger.info(f"Показана история серийного номера {serial} пользователю @{message.from_user.username} (ID: {message.from_user.id})")

@router.callback_query(F.data.startswith("prev_page_") | F.data.startswith("next_page_"))
async def navigate_appeal_page(callback: CallbackQuery, state: FSMContext, **data):
    page = int(callback.data.split("_")[-1])
    data_state = await state.get_data()
    serial = data_state.get('serial')
    history = data_state.get('history')
    serial_data = data_state.get('serial_data')

    if not all([serial, history, serial_data]):
        db_pool = data.get("db_pool")
        if not db_pool:
            logger.error("db_pool отсутствует в data")
            await callback.message.answer("Ошибка сервера. Попробуйте снова.",
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                              [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                          ]))
            return
        serial_data, history = await get_serial_history(serial)
        if not serial_data:
            await callback.message.answer(f"Серийный номер {serial} не найден.",
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                              [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                          ]))
            logger.warning(
                f"Серийный номер {serial} не найден при навигации страниц пользователем @{callback.from_user.username}")
            return
        await state.update_data(serial=serial, history=history, serial_data=serial_data)

    await callback.message.delete()
    await show_appeal_page(callback.message, state, history, page, serial_data)
    await state.update_data(page=page)
    await callback.answer()
    logger.info(
        f"Показана страница {page} истории серийного номера {serial} пользователю @{callback.from_user.username} (ID: {callback.from_user.id})")