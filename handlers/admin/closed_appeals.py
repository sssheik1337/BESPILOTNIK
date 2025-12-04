from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.db import get_closed_appeals, get_appeal
from utils.statuses import APPEAL_STATUSES
from datetime import datetime
from utils.logger import get_logger

logger = get_logger(__name__)

router = Router()


async def get_closed_appeals_menu(appeals):
    keyboard = []
    for appeal in appeals:
        closed_time = appeal["closed_time"]
        if closed_time:
            try:
                closed_time = datetime.strptime(closed_time, "%Y-%m-%dT%H:%M").strftime(
                    "%Y-%m-%d %H:%M"
                )
            except ValueError:
                closed_time = "Неизвестно"
        else:
            closed_time = "Не указано"
        text = f"№{appeal['appeal_id']} ({closed_time})"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=text, callback_data=f"view_closed_appeal_{appeal['appeal_id']}"
                )
            ]
        )
    return keyboard


@router.callback_query(F.data == "closed_appeals")
async def show_closed_appeals(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        return
    appeals, total = await get_closed_appeals(page=0)
    keyboard = await get_closed_appeals_menu(appeals)
    if not appeals:
        keyboard.append(
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        )
        await callback.message.edit_text(
            "Нет закрытых заявок.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        )
        logger.info(
            f"Нет закрытых заявок для пользователя @{callback.from_user.username}"
        )
        return
    nav_buttons = []
    if total > 10:
        nav_buttons.append(
            InlineKeyboardButton(text="Следующая ➡️", callback_data="next_closed_page_1")
        )
    nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    keyboard.append(nav_buttons)
    await callback.message.edit_text(
        f"Закрытые заявки (страница 1 из {max(1, (total + 9) // 10)}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    logger.info(
        f"Показана страница 0 закрытых заявок пользователю @{callback.from_user.username}"
    )


@router.callback_query(F.data.startswith("view_closed_appeal_"))
async def view_closed_appeal(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal or appeal["status"] != "closed":
        await callback.message.edit_text(
            "Заявка не найдена или не закрыта.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад", callback_data="closed_appeals"
                        )
                    ]
                ]
            ),
        )
        logger.warning(
            f"Заявка №{appeal_id} не найдена или не закрыта пользователем @{callback.from_user.username}"
        )
        return
    closed_time = appeal["closed_time"]
    if closed_time:
        try:
            closed_time = datetime.strptime(closed_time, "%Y-%m-%dT%H:%M").strftime(
                "%Y-%m-%d %H:%M"
            )
        except ValueError:
            closed_time = "Неизвестно"
    else:
        closed_time = "Не указано"
    new_serial_text = (
        f"\nНовый серийник: {appeal['new_serial']}" if appeal["new_serial"] else ""
    )
    response_text = f"\nОтвет: {appeal['response']}" if appeal["response"] else ""
    text = (
        f"Заявка №{appeal['appeal_id']}:\n"
        f"Серийный номер: {appeal['serial']}\n"
        f"Описание: {appeal['description']}\n"
        f"Статус: {APPEAL_STATUSES.get(appeal['status'], appeal['status'])}\n"
        f"Дата закрытия: {closed_time}{new_serial_text}{response_text}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="closed_appeals")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    logger.info(
        f"Пользователь @{callback.from_user.username} просмотрел закрытую заявку №{appeal_id}"
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("next_closed_page_") | F.data.startswith("prev_closed_page_")
)
async def navigate_closed_appeals(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        return
    page = int(callback.data.split("_")[-1])
    appeals, total = await get_closed_appeals(page=page)
    keyboard = await get_closed_appeals_menu(appeals)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="⬅️ Предыдущая", callback_data=f"prev_closed_page_{page - 1}"
            )
        )
    if (page + 1) * 10 < total:
        nav_buttons.append(
            InlineKeyboardButton(
                text="Следующая ➡️", callback_data=f"next_closed_page_{page + 1}"
            )
        )
    nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    keyboard.append(nav_buttons)
    try:
        await callback.message.edit_text(
            f"Закрытые заявки (страница {page + 1} из {max(1, (total + 9) // 10)}):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            logger.debug(
                f"Сообщение не изменено для закрытых заявок, страница {page}, пользователь @{callback.from_user.username}"
            )
        else:
            logger.error(f"Ошибка редактирования сообщения для закрытых заявок: {e}")
            await callback.message.answer(
                f"Закрытые заявки (страница {page + 1} из {max(1, (total + 9) // 10)}):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            )
    logger.info(
        f"Пользователь @{callback.from_user.username} просмотрел закрытые заявки (страница {page}, найдено: {len(appeals)})"
    )
    await callback.answer()
