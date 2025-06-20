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
    user_id = message.from_user.id
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    async with db_pool.acquire() as conn:
        is_employee = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
    if user_id not in MAIN_ADMIN_IDS and not is_employee:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка доступа к истории серийника от неадминистратора @{message.from_user.username} (ID: {user_id})")
        await state.clear()
        return
    serial = message.text
    if not validate_serial(serial):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Неверный формат серийного номера (A-Za-z0-9, 8–20 символов).", reply_markup=keyboard)
        logger.warning(f"Неверный серийный номер {serial} для истории от @{message.from_user.username} (ID: {user_id})")
        await state.clear()
        return
    serial_data, history = await get_serial_history(serial)
    if not history:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("История по серийному номеру отсутствует.", reply_markup=keyboard)
        logger.info(f"История по серийнику {serial} отсутствует, запрос от @{message.from_user.username} (ID: {user_id})")
        await state.clear()
        return
    await state.update_data(serial=serial, history=history, page=0)
    await show_appeal_page(message, state, history, 0, serial_data)
    logger.info(f"История по серийнику {serial} запрошена пользователем @{message.from_user.username} (ID: {user_id})")
    await state.set_state(AdminResponse.serial)

async def show_appeal_page(message: Message, state: FSMContext, history, page, serial_data):
    appeal = history[page]
    upload_date = "Не указана"
    if serial_data['upload_date']:
        try:
            upload_date_dt = datetime.strptime(serial_data['upload_date'], "%Y-%m-%dT%H:%M")
            upload_date = upload_date_dt.strftime("%Y-%m-%d %H:%M")
        except ValueError as e:
            logger.error(f"Ошибка форматирования upload_date: {e}")
            upload_date = serial_data['upload_date']
    taken_time = "Не взято"
    if appeal['taken_time']:
        try:
            taken_time_dt = datetime.strptime(appeal['taken_time'], "%Y-%m-%dT%H:%M")
            taken_time = taken_time_dt.strftime("%Y-%m-%d %H:%M")
        except ValueError as e:
            logger.error(f"Ошибка форматирования taken_time: {e}")
            taken_time = appeal['taken_time']
    new_serial_text = f"\nНовый серийник: {appeal.get('new_serial', '')}" if appeal.get('new_serial') else ""
    response = (f"История по серийному номеру {appeal['serial']}:\n"
                f"Дата загрузки: {upload_date}\n"
                f"Количество обращений: {serial_data['appeal_count']}\n"
                f"Статус возврата/брака: {serial_data['return_status'] or 'Не указан'}\n\n"
                f"Заявка №{appeal['appeal_id']}:\n"
                f"Дата: {taken_time}\n"
                f"Статус: {appeal['status']}\n"
                f"Админ: {appeal['username'] or 'Не назначен'}\n"
                f"Описание: {appeal['description']}\n"
                f"Ответ: {appeal['response'] or 'Нет ответа'}{new_serial_text}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"prev_page_{page-1}"))
    if page < len(history) - 1:
        nav_buttons.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"next_page_{page+1}"))
    if nav_buttons:
        keyboard.inline_keyboard.append(nav_buttons)
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    await message.answer(response, reply_markup=keyboard)

@router.callback_query(F.data.startswith("prev_page_") | F.data.startswith("next_page_"))
async def navigate_appeal_page(callback: CallbackQuery, state: FSMContext, **data):
    page = int(callback.data.split("_")[-1])
    data_state = await state.get_data()
    serial = data_state['serial']
    history = data_state['history']
    serial_data, _ = await get_serial_history(serial)
    await callback.message.delete()
    await show_appeal_page(callback.message, state, history, page, serial_data)
    await state.update_data(page=page)
    await callback.answer()