from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_defect_status_menu
from database.db import get_appeal, add_defect_report
from utils.validators import validate_serial, validate_media
import logging

logger = logging.getLogger(__name__)

router = Router()


class AdminResponse(StatesGroup):
    mark_defect = State()
    defect_status = State()
    new_serial = State()
    response_after_replacement = State()
    defect_serial = State()
    defect_location = State()
    defect_media = State()


@router.callback_query(F.data == "mark_defect")
async def mark_defect_prompt(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Брак", callback_data="defect_status_brak")],
            [
                InlineKeyboardButton(
                    text="Возврат", callback_data="defect_status_vozvrat"
                )
            ],
            [InlineKeyboardButton(text="Замена", callback_data="defect_status_zamena")],
            [
                InlineKeyboardButton(
                    text="Добавить отчёт о неисправности",
                    callback_data="add_defect_report",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )
    await callback.message.edit_text(
        "Выберите статус для устройства или добавьте отчёт:", reply_markup=keyboard
    )
    await state.set_state(AdminResponse.defect_status)
    logger.debug(f"Запрос отметки статуса или отчёта от @{callback.from_user.username}")


@router.callback_query(F.data == "add_defect_report")
async def add_defect_report_prompt(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mark_defect")]
        ]
    )
    await callback.message.edit_text(
        "Введите серийный номер для отчёта:", reply_markup=keyboard
    )
    await state.set_state(AdminResponse.defect_serial)
    logger.debug(
        f"Запрос добавления отчёта о неисправности от @{callback.from_user.username}"
    )


@router.message(StateFilter(AdminResponse.defect_serial))
async def process_defect_serial(message: Message, state: FSMContext, **data):
    serial = message.text.strip()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mark_defect")]
        ]
    )
    if not validate_serial(serial):
        await message.answer(
            "Неверный формат серийного номера. Попробуйте снова:", reply_markup=keyboard
        )
        logger.warning(
            f"Неверный серийный номер {serial} от @{message.from_user.username} (ID: {message.from_user.id})"
        )
        return
    db_pool = data["db_pool"]
    async with db_pool.acquire() as conn:
        serial_exists = await conn.fetchrow(
            "SELECT * FROM serials WHERE serial = $1", serial
        )
    if not serial_exists:
        await message.answer(
            "Серийный номер не найден в базе. Попробуйте снова:", reply_markup=keyboard
        )
        logger.warning(
            f"Серийный номер {serial} не найден, попытка от @{message.from_user.username} (ID: {message.from_user.id})"
        )
        return
    await state.update_data(
        serial=serial, employee_id=message.from_user.id, media_links=[]
    )
    await message.answer("Введите место неисправности:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_location)
    logger.debug(
        f"Серийный номер {serial} для отчёта принят от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.message(StateFilter(AdminResponse.defect_location))
async def process_defect_location(message: Message, state: FSMContext):
    location = message.text.strip()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_defect_media")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mark_defect")],
        ]
    )
    await state.update_data(location=location)
    await message.answer(
        "Прикрепите медиафайлы (до 10, или 'Готово'):", reply_markup=keyboard
    )
    await state.set_state(AdminResponse.defect_media)
    logger.debug(
        f"Место неисправности {location} введено от @{message.from_user.username}"
    )


@router.message(StateFilter(AdminResponse.defect_media))
async def process_defect_media(message: Message, state: FSMContext):
    data_state = await state.get_data()
    media_links = data_state.get("media_links", [])
    if len(media_links) >= 10:
        await message.answer(
            "Достигнуто максимальное количество медиа (10). Нажмите 'Готово'."
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="submit_defect_report")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mark_defect")],
        ]
    )
    is_valid, media = validate_media(message)
    if is_valid:
        media_links.extend(media)
        await state.update_data(media_links=media_links)
        await message.answer(
            f"Медиа добавлено ({len(media_links)}/10). Приложите ещё или нажмите 'Готово':",
            reply_markup=keyboard,
        )
        logger.debug(
            f"Медиа ({media[0]['type']}) добавлено для отчёта от @{message.from_user.username}"
        )
    else:
        await message.answer(
            "Неподдерживаемый формат. Приложите фото (png/jpeg), видео (mp4) или кружочек (mp4).",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Неподдерживаемый формат медиа для отчёта от @{message.from_user.username}"
        )


@router.callback_query(F.data == "done_defect_media")
async def submit_defect_report(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data["db_pool"]
    data_state = await state.get_data()
    serial = data_state.get("serial")
    location = data_state.get("location")
    employee_id = data_state.get("employee_id")
    media_links = data_state.get("media_links", [])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mark_defect")]
        ]
    )
    await add_defect_report(serial, location, employee_id, media_links)
    await callback.message.delete()
    await callback.message.answer(
        "Отчёт о неисправности добавлен.", reply_markup=keyboard
    )
    await state.clear()
    logger.info(
        f"Отчёт о неисправности для серийника {serial} добавлен @{callback.from_user.username}"
    )


@router.callback_query(F.data.startswith("mark_defect_"))
async def mark_defect_from_appeal(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
                ]
            ),
        )
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.edit_text(
            "Заявка не найдена.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
                ]
            ),
        )
        logger.warning(
            f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}"
        )
        return
    serial = appeal["serial"]
    await state.update_data(serial=serial, appeal_id=appeal_id)
    keyboard = get_defect_status_menu(serial)
    await callback.message.edit_text(
        "Выберите статус для устройства:", reply_markup=keyboard
    )
    await state.set_state(AdminResponse.defect_status)
    logger.debug(
        f"Пользователь @{callback.from_user.username} начал отметку статуса для заявки №{appeal_id} с серийником {serial}"
    )


@router.callback_query(F.data.startswith("defect_status_"))
async def process_defect_status(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
                ]
            ),
        )
        return
    parts = callback.data.split("_")
    status = parts[2]  # brak, vozvrat, zamena
    serial = parts[3]
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE serials SET return_status = $1 WHERE serial = $2", status, serial
        )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]
    )
    await callback.message.edit_text(
        f"Серийный номер {serial} отмечен как {status}.", reply_markup=keyboard
    )
    logger.info(
        f"Серийный номер {serial} отмечен как {status} пользователем @{callback.from_user.username}"
    )
    await state.clear()


@router.callback_query(F.data.startswith("complete_replacement_"))
async def complete_replacement_prompt(
    callback: CallbackQuery, state: FSMContext, **data
):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
                ]
            ),
        )
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal or appeal["status"] != "replacement_process":
        await callback.message.edit_text(
            "Заявка не найдена или не в процессе замены.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
                ]
            ),
        )
        logger.warning(
            f"Заявка №{appeal_id} не найдена или не в статусе 'replacement_process' для пользователя @{callback.from_user.username}"
        )
        return
    await state.update_data(appeal_id=appeal_id, old_serial=appeal["serial"])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}"
                )
            ]
        ]
    )
    await callback.message.edit_text(
        "Введите новый серийный номер для замены:", reply_markup=keyboard
    )
    await state.set_state(AdminResponse.new_serial)
    logger.debug(
        f"Пользователь @{callback.from_user.username} начал ввод нового серийного номера для заявки №{appeal_id}"
    )
