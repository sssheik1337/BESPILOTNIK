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
    serial = message.text.strip()
    if not validate_serial(serial):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Неверный формат серийного номера. Попробуйте снова:", reply_markup=keyboard)
        logger.warning(f"Неверный формат серийного номера {serial} от @{message.from_user.username}")
        return
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    serial_data, appeals = await get_serial_history(serial)
    if not serial_data:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer(f"Серийный номер {serial} не найден.", reply_markup=keyboard)
        logger.warning(f"Серийный номер {serial} не найден пользователем @{message.from_user.username}")
        return
    await state.update_data(serial=serial, history=appeals, serial_data=serial_data, page=0)
    await show_appeal_page(message, state, appeals, 0, serial_data)
    logger.info(f"История по серийному номеру {serial} показана пользователю @{message.from_user.username} (ID: {message.from_user.id})")

async def show_appeal_page(message: Message, state: FSMContext, history: list, page: int, serial_data: dict):
    appeal = history[page]
    upload_date = serial_data['upload_date']
    # Проверка на None для upload_date
    if upload_date:
        try:
            upload_date_dt = datetime.strptime(upload_date, "%Y-%m-%dT%H:%M")
            upload_date = upload_date_dt.strftime("%d.%m.%Y %H:%M")
        except Exception as e:
            logger.error(f"Ошибка форматирования upload_date: {e}")
            upload_date = upload_date  # Оставляем как есть, если не удалось преобразовать
    else:
        upload_date = "Не указана"

    taken_time = appeal['taken_time']
    if taken_time:
        try:
            taken_time_dt = datetime.strptime(taken_time, "%Y-%m-%dT%H:%M")
            taken_time = taken_time_dt.strftime("%d.%m.%Y %H:%M")
        except Exception as e:
            logger.error(f"Ошибка форматирования taken_time: {e}")
            taken_time = taken_time
    else:
        taken_time = "Не указана"

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
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"prev_page_{page - 1}"))
    if page < len(history) - 1:
        nav_buttons.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"next_page_{page + 1}"))
    if nav_buttons:
        keyboard.inline_keyboard.append(nav_buttons)
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    await message.answer(response, reply_markup=keyboard)

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