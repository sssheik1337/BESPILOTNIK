from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_overdue_menu
from database.db import get_appeal, get_db_pool
from config import MAIN_ADMIN_IDS
import asyncio
import logging

logger = logging.getLogger(__name__)

router = Router()

class AdminResponse(StatesGroup):
    new_time = State()

async def check_overdue(appeal_id, bot, hours=1):
    await asyncio.sleep(hours * 60)
    db_pool = await get_db_pool()
    appeal = await get_appeal(appeal_id)
    if appeal["status"] == "in_progress":
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE appeals SET status = $1 WHERE appeal_id = $2", "overdue", appeal_id)
        for main_admin_id in MAIN_ADMIN_IDS:
            text = (f"Заявка №{appeal_id} просрочена.\n"
                    f"Серийный номер: {appeal['serial']}\n"
                    f"Описание: {appeal['description']}\n"
                    f"Статус: {APPEAL_STATUSES.get(appeal['status'], appeal['status'])}\n"
                    f"Дата создания: {appeal['created_time']}")
            await bot.send_message(
                main_admin_id,
                text,
                reply_markup=get_overdue_menu(appeal_id)
            )
        logger.info(f"Заявка №{appeal_id} просрочена")

async def check_delegated_overdue(appeal_id, bot, employee_id):
    await asyncio.sleep(12 * 60)
    db_pool = await get_db_pool()
    appeal = await get_appeal(appeal_id)
    if appeal["status"] in ["in_progress", "postponed", "replacement_process"] and appeal["admin_id"] == employee_id:
        for main_admin_id in MAIN_ADMIN_IDS:
            await bot.send_message(
                main_admin_id,
                f"Сотрудник ID {employee_id} не ответил на делегированную заявку №{appeal_id} в течение 12 минут.",
                reply_markup=get_overdue_menu(appeal_id)
            )
        logger.info(f"Делегированная заявка №{appeal_id} не обработана сотрудником ID {employee_id}")

@router.callback_query(F.data.startswith("set_new_time_"))
async def set_new_time_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка установки времени просрочки от неадминистратора @{callback.from_user.username}")
        return
    appeal_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите новое время просрочки в часах:", reply_markup=keyboard)
    await state.set_state(AdminResponse.new_time)
    await state.update_data(appeal_id=appeal_id)
    logger.debug(f"Запрос установки времени просрочки для заявки №{appeal_id} от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.new_time))
async def process_new_time(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    try:
        hours = float(message.text)
        data_state = await state.get_data()
        appeal_id = data_state["appeal_id"]
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE appeals SET status = $1 WHERE appeal_id = $2", "in_progress", appeal_id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer(f"Новое время просрочки установлено: {hours} часов.", reply_markup=keyboard)
        logger.info(f"Время просрочки для заявки №{appeal_id} установлено на {hours} часов пользователем @{message.from_user.username}")
        await check_overdue(appeal_id, message.bot, hours)
        await state.clear()
    except ValueError:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Введите число часов.", reply_markup=keyboard)
        logger.error(f"Неверный формат времени просрочки от @{message.from_user.username}")