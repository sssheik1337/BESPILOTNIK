from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_defect_status_menu
from database.db import mark_defect, start_replacement, complete_replacement, get_replacement_appeals, get_appeal
from utils.validators import validate_serial
import logging
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

router = Router()

class AdminResponse(StatesGroup):
    mark_defect = State()
    defect_status = State()
    new_serial = State()
    response_after_replacement = State()

@router.callback_query(F.data == "mark_defect")
async def mark_defect_prompt(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Брак", callback_data="defect_status_brak")],
        [InlineKeyboardButton(text="Возврат", callback_data="defect_status_vozvrat")],
        [InlineKeyboardButton(text="Замена", callback_data="defect_status_zamena")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Выберите статус для устройства:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_status)
    logger.debug(f"Запрос отметки статуса от @{callback.from_user.username}")

@router.callback_query(F.data.startswith("mark_defect_"))
async def mark_defect_from_appeal(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.edit_text("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    serial = appeal["serial"]
    await state.update_data(serial=serial, appeal_id=appeal_id)
    keyboard = get_defect_status_menu(serial)
    await callback.message.edit_text("Выберите статус для устройства:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_status)
    logger.debug(f"Пользователь @{callback.from_user.username} начал отметку статуса для заявки №{appeal_id} с серийником {serial}")

@router.message(StateFilter(AdminResponse.mark_defect))
async def process_mark_defect(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    serial = message.text
    if not validate_serial(serial):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Неверный формат серийного номера (A-Za-z0-9, 8–20 символов).", reply_markup=keyboard)
        logger.warning(f"Неверный серийный номер {serial} от @{message.from_user.username}")
        return
    data_state = await state.get_data()
    status = data_state.get('status')
    await mark_defect(serial, status.capitalize())
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await message.answer(f"Серийный номер {serial} отмечен как {status.capitalize()}.", reply_markup=keyboard)
    logger.info(f"Серийный номер {serial} отмечен как {status.capitalize()} пользователем @{message.from_user.username}")
    await state.clear()

@router.callback_query(F.data.startswith("defect_status_"))
async def process_defect_status(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    status = callback.data.split("_")[2]
    if status in ["brak", "vozvrat"]:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Введите серийный номер устройства:", reply_markup=keyboard)
        await state.set_state(AdminResponse.mark_defect)
        await state.update_data(status=status)
        logger.debug(f"Пользователь @{callback.from_user.username} выбрал статус {status} для отметки")
    elif status == "zamena":
        appeals = await get_replacement_appeals()
        if not appeals:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ])
            await callback.message.edit_text("Нет активных заявок для замены.", reply_markup=keyboard)
            logger.info(f"Нет заявок для замены для пользователя @{callback.from_user.username}")
            await state.clear()
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for appeal in appeals:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"Заявка №{appeal['appeal_id']} ({appeal['serial']})",
                    callback_data=f"select_appeal_{appeal['appeal_id']}"
                )
            ])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
        await callback.message.edit_text("Выберите заявку для замены устройства:", reply_markup=keyboard)
        await state.set_state(AdminResponse.defect_status)
        logger.debug(f"Пользователь @{callback.from_user.username} выбирает заявку для замены")
    await callback.answer()

@router.callback_query(F.data.startswith("select_appeal_"))
async def select_appeal_for_replacement(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[2])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.edit_text("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    await start_replacement(appeal_id, appeal["serial"])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await callback.message.edit_text(
        f"Заявка №{appeal_id} переведена в статус 'процесс замены'. Введите новый серийный номер:",
        reply_markup=keyboard
    )
    await state.set_state(AdminResponse.new_serial)
    await state.update_data(appeal_id=appeal_id, old_serial=appeal["serial"])
    logger.info(f"Заявка №{appeal_id} переведена в статус 'процесс замены' для серийника {appeal['serial']} пользователем @{callback.from_user.username}")
    await callback.answer()

@router.message(StateFilter(AdminResponse.new_serial))
async def process_new_serial(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
        ]))
        return
    new_serial = message.text
    if not validate_serial(new_serial):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
        ])
        await message.answer("Неверный формат серийного номера (A-Za-z0-9, 8–20 символов).", reply_markup=keyboard)
        logger.warning(f"Неверный формат нового серийного номера {new_serial} от @{message.from_user.username}")
        return
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    old_serial = data_state["old_serial"]
    try:
        async with db_pool.acquire() as conn:
            serial_exists = await conn.fetchrow(
                "SELECT serial FROM serials WHERE serial = $1", new_serial
            )
        if not serial_exists:
            raise ValueError(f"Новый серийный номер {new_serial} не найден в базе")
        await state.update_data(new_serial=new_serial)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_replacement")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer("Введите ответ для пользователя (или нажмите 'Готово' для завершения):", reply_markup=keyboard)
        await state.set_state(AdminResponse.response_after_replacement)
        logger.debug(f"Пользователь @{message.from_user.username} начал ввод ответа для замены в заявке №{appeal_id}")
    except ValueError as e:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(f"Ошибка при замене серийника для заявки №{appeal_id}: {str(e)}")
        await state.clear()
    except Exception as e:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer("Произошла ошибка при замене устройства. Попробуйте позже.", reply_markup=keyboard)
        logger.error(f"Неизвестная ошибка при замене серийника для заявки №{appeal_id}: {str(e)}")
        await state.clear()

@router.callback_query(F.data == "done_replacement")
async def process_done_replacement(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
        ]))
        return
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    new_serial = data_state["new_serial"]
    old_serial = data_state["old_serial"]
    try:
        await complete_replacement(appeal_id, new_serial, response=None)
        appeal = await get_appeal(appeal_id)
        text = f"Ваше устройство с серийным номером {old_serial} заменено на новое с серийным номером {new_serial}."
        try:
            await callback.message.bot.send_message(
                chat_id=appeal["user_id"],
                text=text
            )
            logger.debug(f"Уведомление о замене отправлено пользователю ID {appeal['user_id']} для заявки №{appeal_id}")
        except TelegramBadRequest as e:
            logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {e}")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await callback.message.edit_text(f"Замена завершена. Новый серийный номер {new_serial} добавлен.", reply_markup=keyboard)
        logger.info(f"Замена завершена для заявки №{appeal_id}, новый серийник: {new_serial}, ответ: None, пользователь: @{callback.from_user.username}")
        await state.clear()
    except ValueError as e:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await callback.message.edit_text(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(f"Ошибка при замене серийника для заявки №{appeal_id}: {str(e)}")
        await state.clear()
    except Exception as e:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await callback.message.edit_text("Произошла ошибка при замене устройства. Попробуйте позже.", reply_markup=keyboard)
        logger.error(f"Неизвестная ошибка при замене серийника для заявки №{appeal_id}: {str(e)}")
        await state.clear()
    await callback.answer()

@router.message(StateFilter(AdminResponse.response_after_replacement))
async def process_response_after_replacement(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
        ]))
        return
    response = message.text.strip() if message.text else None
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    new_serial = data_state["new_serial"]
    old_serial = data_state["old_serial"]
    try:
        await complete_replacement(appeal_id, new_serial, response)
        appeal = await get_appeal(appeal_id)
        text = f"Ваше устройство с серийным номером {old_serial} заменено на новое с серийным номером {new_serial}."
        if response:
            text += f"\nОтвет: {response}"
        try:
            await message.bot.send_message(
                chat_id=appeal["user_id"],
                text=text
            )
            logger.debug(f"Уведомление о замене отправлено пользователю ID {appeal['user_id']} для заявки №{appeal_id}")
        except TelegramBadRequest as e:
            logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {e}")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer(f"Замена завершена. Новый серийный номер {new_serial} добавлен.", reply_markup=keyboard)
        logger.info(f"Замена завершена для заявки №{appeal_id}, новый серийник: {new_serial}, ответ: {response}, пользователь: @{message.from_user.username}")
        await state.clear()
    except ValueError as e:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(f"Ошибка при замене серийника для заявки №{appeal_id}: {str(e)}")
        await state.clear()
    except Exception as e:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer("Произошла ошибка при замене устройства. Попробуйте позже.", reply_markup=keyboard)
        logger.error(f"Неизвестная ошибка при замене серийника для заявки №{appeal_id}: {str(e)}")
        await state.clear()

@router.callback_query(F.data.startswith("complete_replacement_"))
async def complete_replacement_prompt(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal or appeal["status"] != "replacement_process":
        await callback.message.edit_text("Заявка не найдена или не в процессе замены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена или не в статусе 'replacement_process' для пользователя @{callback.from_user.username}")
        return
    await state.update_data(appeal_id=appeal_id, old_serial=appeal["serial"])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await callback.message.edit_text("Введите новый серийный номер для замены:", reply_markup=keyboard)
    await state.set_state(AdminResponse.new_serial)
    logger.debug(f"Пользователь @{callback.from_user.username} начал ввод нового серийного номера для заявки №{appeal_id}")