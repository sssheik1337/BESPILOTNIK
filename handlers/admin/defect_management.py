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
from database.db import get_appeal, add_defect_report, mark_defect
from utils.validators import validate_serial, validate_media
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

router = Router()


DEFECT_ACTION_LABELS = {
    "repair": "Ремонт",
    "replacement": "Замена",
}


class AdminResponse(StatesGroup):
    mark_defect = State()
    defect_status = State()
    defect_serial = State()
    defect_action = State()
    defect_new_serial = State()
    defect_confirm_serial = State()
    defect_location = State()
    defect_comment = State()
    defect_media = State()


@router.callback_query(F.data == "mark_defect")
async def mark_defect_prompt(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ремонт", callback_data="defect_status_repair"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Замена", callback_data="defect_status_replacement"
                )
            ],
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
        "Выберите статус устройства или добавьте отчёт:", reply_markup=keyboard
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
        serial=serial,
        employee_id=message.from_user.id,
        media_links=[],
        action=None,
        new_serial=None,
        comment=None,
        return_callback="mark_defect",
    )
    action_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ремонт", callback_data="dm_action_repair")],
            [InlineKeyboardButton(text="Замена", callback_data="dm_action_replacement")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mark_defect")],
        ]
    )
    await message.answer(
        "Выберите действие: ремонт или замена.", reply_markup=action_keyboard
    )
    await state.set_state(AdminResponse.defect_action)
    logger.debug(
        f"Серийный номер {serial} для отчёта принят от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.callback_query(
    StateFilter(AdminResponse.defect_action),
    F.data.in_({"dm_action_repair", "dm_action_replacement"}),
)
async def choose_defect_action_dm(callback: CallbackQuery, state: FSMContext):
    action = "repair" if callback.data.endswith("repair") else "replacement"
    await state.update_data(action=action)
    data_state = await state.get_data()
    return_callback = data_state.get("return_callback", "mark_defect")
    if action == "replacement":
        await callback.message.edit_text(
            "Введите серийный номер нового устройства:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]
                ]
            ),
        )
        await state.set_state(AdminResponse.defect_new_serial)
    else:
        await callback.message.edit_text(
            "Укажите место проведения работ:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]
                ]
            ),
        )
        await state.set_state(AdminResponse.defect_location)
    await callback.answer()


@router.message(StateFilter(AdminResponse.defect_new_serial))
async def process_new_serial_dm(message: Message, state: FSMContext):
    new_serial = (message.text or "").strip()
    data_state = await state.get_data()
    return_callback = data_state.get("return_callback", "mark_defect")
    if not validate_serial(new_serial):
        await message.answer(
            "Неверный формат серийного номера. Попробуйте снова:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]]
            ),
        )
        return
    await state.update_data(new_serial_candidate=new_serial)
    await message.answer(
        "Повторите серийный номер нового устройства для подтверждения:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]]
        ),
    )
    await state.set_state(AdminResponse.defect_confirm_serial)


@router.message(StateFilter(AdminResponse.defect_confirm_serial))
async def confirm_new_serial_dm(message: Message, state: FSMContext):
    confirmation = (message.text or "").strip()
    data_state = await state.get_data()
    expected = data_state.get("new_serial_candidate")
    return_callback = data_state.get("return_callback", "mark_defect")
    if confirmation != expected:
        await message.answer(
            "Серийные номера не совпадают. Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]]
            ),
        )
        await state.set_state(AdminResponse.defect_new_serial)
        return
    await state.update_data(new_serial=confirmation, new_serial_candidate=None)
    await message.answer(
        "Укажите место проведения работ:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]]
        ),
    )
    await state.set_state(AdminResponse.defect_location)


@router.message(StateFilter(AdminResponse.defect_location))
async def process_defect_location(message: Message, state: FSMContext):
    location = (message.text or "").strip()
    data_state = await state.get_data()
    return_callback = data_state.get("return_callback", "mark_defect")
    if not location:
        await message.answer(
            "Место не может быть пустым. Укажите место проведения работ:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]]
            ),
        )
        return
    await state.update_data(location=location)
    await message.answer(
        "Добавьте комментарий к отчёту:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]]
        ),
    )
    await state.set_state(AdminResponse.defect_comment)
    logger.debug(
        "Место неисправности %s введено от @%s",
        location,
        message.from_user.username,
    )


@router.message(StateFilter(AdminResponse.defect_comment))
async def process_defect_comment_dm(message: Message, state: FSMContext):
    comment = (message.text or "").strip()
    data_state = await state.get_data()
    return_callback = data_state.get("return_callback", "mark_defect")
    if not comment:
        await message.answer(
            "Комментарий не может быть пустым. Добавьте комментарий:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]]
            ),
        )
        return
    await state.update_data(comment=comment)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_defect_media")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)],
        ]
    )
    await message.answer(
        "Прикрепите медиафайлы (до 10, или 'Готово'):", reply_markup=keyboard
    )
    await state.set_state(AdminResponse.defect_media)
    logger.debug(
        "Комментарий для отчёта о дефекте получен от @%s",
        message.from_user.username,
    )


@router.message(StateFilter(AdminResponse.defect_media))
async def process_defect_media(message: Message, state: FSMContext):
    data_state = await state.get_data()
    media_links = data_state.get("media_links", [])
    return_callback = data_state.get("return_callback", "mark_defect")
    if len(media_links) >= 10:
        await message.answer(
            "Достигнуто максимальное количество медиа (10). Нажмите 'Готово'.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]]
            ),
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_defect_media")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)],
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
    action = data_state.get("action")
    comment = data_state.get("comment")
    new_serial = data_state.get("new_serial")
    media_links = data_state.get("media_links", [])
    return_callback = data_state.get("return_callback", "mark_defect")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=return_callback)]
        ]
    )
    if (
        not serial
        or not location
        or not action
        or not comment
        or (action == "replacement" and not new_serial)
    ):
        await callback.message.edit_text(
            "Не удалось сохранить отчёт: заполните все поля.",
            reply_markup=keyboard,
        )
        await state.clear()
        return
    now = datetime.now()
    await add_defect_report(
        serial,
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M"),
        location,
        json.dumps(media_links),
        employee_id,
        action,
        new_serial=new_serial,
        comment=comment,
    )
    await callback.message.delete()
    await callback.message.answer(
        "Отчёт о неисправности добавлен.", reply_markup=keyboard
    )
    await state.clear()
    logger.info(
        "Отчёт о неисправности для серийника %s добавлен @%s",
        serial,
        callback.from_user.username,
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
    await state.update_data(
        serial=serial, appeal_id=appeal_id, return_callback=f"view_appeal_{appeal_id}"
    )
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
    status_key = parts[2]
    serial = parts[3]
    if status_key not in {"repair", "replacement"}:
        await callback.answer("Неизвестный статус", show_alert=True)
        return
    await mark_defect(serial, status_key)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]
    )
    status_label = DEFECT_ACTION_LABELS.get(status_key, status_key)
    await callback.message.edit_text(
        f"Серийный номер {serial} отмечен как {status_label}.", reply_markup=keyboard
    )
    logger.info(
        "Серийный номер %s отмечен как %s пользователем @%s",
        serial,
        status_label,
        callback.from_user.username,
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
