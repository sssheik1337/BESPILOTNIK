from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_admin_menu, get_base_management_menu, get_admin_panel_menu, get_overdue_menu, get_open_appeals_menu, get_my_appeals_menu, get_remove_channel_menu, get_edit_channel_menu, get_appeal_actions_menu, get_notification_menu, get_response_menu, get_defect_status_menu
from database.db import get_serial_history, get_appeal, take_appeal, postpone_appeal, save_response, close_appeal, delegate_appeal, get_open_appeals, get_assigned_appeals, add_admin, add_notification_channel, get_notification_channels, get_admins, mark_defect, start_replacement, complete_replacement, get_replacement_appeals, get_db_pool
from utils.excel_utils import import_serials, export_serials
from utils.validators import validate_serial
from config import MAIN_ADMIN_IDS
from datetime import datetime
import asyncio
import json
from aiogram.exceptions import TelegramBadRequest
import logging

logger = logging.getLogger(__name__)

router = Router()

class AdminResponse(StatesGroup):
    response = State()
    delegate = State()
    new_time = State()
    add_channel = State()
    edit_channel = State()
    add_employee = State()
    mark_defect = State()
    serial = State()
    defect_status = State()
    new_serial = State()
    continue_dialogue = State()

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
            upload_date_dt = datetime.strptime(serial_data['upload_date'], "%Y-%m-%dT%H:%M:%S.%f")
            upload_date = upload_date_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            logger.error(f"Ошибка форматирования upload_date: {e}")
            upload_date = serial_data['upload_date']
    taken_time = "Не взято"
    if appeal['taken_time']:
        try:
            taken_time_dt = datetime.strptime(appeal['taken_time'], "%Y-%m-%dT%H:%M:%S.%f")
            taken_time = taken_time_dt.strftime("%Y-%m-%d %H:%M:%S")
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

@router.callback_query(F.data.startswith("take_appeal_"))
async def take_appeal_callback(callback: CallbackQuery, state: FSMContext, **data):
    try:
        db_pool = data.get("db_pool")
        if not db_pool:
            logger.error("db_pool отсутствует в data")
            await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]))
            return

        user_id = callback.from_user.id
        async with db_pool.acquire() as conn:
            is_employee = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
        if user_id not in MAIN_ADMIN_IDS and not is_employee:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ])
            await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
            logger.warning(f"Попытка взятия заявки от неавторизованного пользователя @{callback.from_user.username} (ID: {user_id})")
            return

        appeal_id = int(callback.data.split("_")[-1])
        appeal = await get_appeal(appeal_id)
        if appeal['status'] not in ["new", "postponed", "overdue", "replacement_process"]:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ])
            await callback.message.edit_text(
                f"Заявка №{appeal_id} уже взята в работу или имеет другой статус.",
                reply_markup=keyboard
            )
            logger.info(f"Попытка повторного взятия заявки №{appeal_id} пользователем @{callback.from_user.username} (ID: {user_id})")
            return

        admin_id = user_id
        await take_appeal(appeal_id, admin_id)
        appeal = await get_appeal(appeal_id)
        channels = await get_notification_channels()
        user_full_name = f"{callback.from_user.first_name} {callback.from_user.last_name or ''}".strip()
        channel_text = (f"Заявка №{appeal_id} взята в работу.\n"
                        f"Исполнитель: {user_full_name}, @{callback.from_user.username}\n"
                        f"Серийный номер: {appeal['serial']}\n"
                        f"Описание: {appeal['description']}")
        is_channel = False
        for channel in channels:
            if callback.message.chat.id == channel["channel_id"]:
                try:
                    await callback.message.edit_text(channel_text)
                    logger.debug(f"Исходное сообщение о заявке №{appeal_id} отредактировано в канал {channel['channel_name']} (ID: {channel['channel_id']})")
                    is_channel = True
                except TelegramBadRequest as e:
                    logger.error(f"Ошибка редактирования сообщения в канал {channel['channel_name']} (ID: {channel['channel_id']}) для заявки №{appeal_id}: {str(e)}")
        if not is_channel:
            try:
                await callback.message.edit_text(
                    f"Обращение №{appeal_id} взято в работу @{callback.from_user.username}\n\n"
                    f"Серийный номер: {appeal['serial']}\n"
                    f"Описание: {appeal['description']}",
                    reply_markup=get_appeal_actions_menu(appeal_id, appeal['status'])
                )
                logger.debug(f"Сообщение для администратора отредактировано для заявки №{appeal_id} в чате {callback.message.chat.id}")
            except TelegramBadRequest as e:
                logger.error(f"Ошибка редактирования сообщения для администратора в чате {callback.message.chat.id} для заявки №{appeal_id}: {str(e)}")
        media_files = json.loads(appeal["media_files"]) if appeal["media_files"] else []
        media_group = []
        for media in media_files:
            if media["type"] == "photo" and media.get("file_id"):
                media_group.append(InputMediaPhoto(media=media["file_id"]))
            elif media["type"] in ["video", "video_note"] and media.get("file_id"):
                media_group.append(InputMediaVideo(media=media["file_id"]))
        text = (f"Ваша заявка №{appeal_id} взята в работу.\n"
                f"Серийный номер: {appeal['serial']}\n"
                f"Описание: {appeal['description']}")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        try:
            if media_group:
                await callback.message.bot.send_media_group(
                    chat_id=appeal["user_id"],
                    media=media_group
                )
            await callback.message.bot.send_message(
                chat_id=appeal["user_id"],
                text=text,
                reply_markup=keyboard
            )
            logger.debug(f"Уведомление отправлено пользователю ID {appeal['user_id']} для заявки №{appeal_id}")
        except TelegramBadRequest as e:
            logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
        logger.info(f"Заявка №{appeal_id} взята в работу пользователем @{callback.from_user.username} (ID: {admin_id})")
        asyncio.create_task(check_overdue(appeal_id, callback.message.bot))
    except Exception as e:
        logger.error(f"Ошибка в take_appeal_callback: {str(e)}")
        await callback.message.edit_text("Ошибка при взятии заявки. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))

@router.callback_query(F.data.startswith("postpone_appeal_"))
async def postpone_appeal_notification(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    await postpone_appeal(appeal_id)
    await callback.message.edit_text(
        f"Заявка №{appeal_id} отложена @{callback.from_user.username}",
        reply_markup=get_notification_menu(appeal_id)
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.answer("Заявка отложена. Вернитесь позже.", reply_markup=keyboard)
    logger.info(f"Заявка №{appeal_id} отложена пользователем @{callback.from_user.username}")

@router.callback_query(F.data.startswith("respond_appeal_"))
async def respond_appeal(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    await callback.message.edit_text(
        "Введите ответ по решению проблемы:",
        reply_markup=get_response_menu(appeal_id)
    )
    await state.set_state(AdminResponse.response)
    await state.update_data(appeal_id=appeal_id)
    logger.debug(f"Запрос ответа для заявки №{appeal_id} от пользователя @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.response))
async def process_response(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    appeal = await get_appeal(appeal_id)
    await save_response(appeal_id, message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Закрыть заявку", callback_data=f"close_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="💬 Продолжить диалог", callback_data=f"continue_dialogue_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await message.answer("Ответ сохранён. Закройте заявку, продолжите диалог или вернитесь в меню:", reply_markup=keyboard)
    await state.clear()
    logger.info(f"Ответ для заявки №{appeal_id} сохранён пользователем @{message.from_user.username}")

@router.callback_query(F.data.startswith("continue_dialogue_"))
async def continue_dialogue(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    await callback.message.edit_text(
        "Введите дополнительный ответ для пользователя:",
        reply_markup=get_response_menu(appeal_id)
    )
    await state.set_state(AdminResponse.continue_dialogue)
    await state.update_data(appeal_id=appeal_id)
    logger.debug(f"Запрос продолжения диалога для заявки №{appeal_id} от пользователя @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.continue_dialogue))
async def process_continue_dialogue(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    appeal = await get_appeal(appeal_id)
    await save_response(appeal_id, appeal['response'] + "\n" + message.text)
    try:
        await message.bot.send_message(
            chat_id=appeal["user_id"],
            text=f"Новый ответ по заявке №{appeal_id}:\n{message.text}"
        )
        logger.debug(f"Уведомление отправлено пользователю ID {appeal['user_id']} для заявки №{appeal_id}")
    except TelegramBadRequest as e:
        logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Закрыть заявку", callback_data=f"close_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="💬 Продолжить диалог", callback_data=f"continue_dialogue_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await message.answer("Ответ отправлен пользователю. Закройте заявку, продолжите диалог или вернитесь в меню:", reply_markup=keyboard)
    await state.clear()
    logger.info(f"Дополнительный ответ для заявки №{appeal_id} отправлен пользователем @{message.from_user.username}")

@router.callback_query(F.data.startswith("close_appeal_"))
async def close_appeal(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    logger.debug(f"Извлечён ответ для заявки №{appeal_id}: {appeal['response']}")
    await close_appeal(appeal_id)
    media_files = json.loads(appeal["media_files"]) if appeal["media_files"] else []
    media_group = []
    for media in media_files:
        if media["type"] == "photo" and media.get("file_id"):
            media_group.append(InputMediaPhoto(media=media["file_id"]))
        elif media["type"] in ["video", "video_note"] and media.get("file_id"):
            media_group.append(InputMediaVideo(media=media["file_id"]))
    response_text = appeal['response'] if appeal['response'] is not None else "Ответ отсутствует"
    new_serial_text = f"\nНовый серийник: {appeal.get('new_serial', '')}" if appeal.get('new_serial') else ""
    text = (f"Ваша заявка №{appeal_id} закрыта.\n"
            f"Серийный номер: {appeal['serial']}\n"
            f"Описание: {appeal['description']}\n"
            f"Ответ: {response_text}{new_serial_text}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    try:
        if media_group:
            await callback.message.bot.send_media_group(
                chat_id=appeal["user_id"],
                media=media_group
            )
        await callback.message.bot.send_message(
            chat_id=appeal["user_id"],
            text=text,
            reply_markup=keyboard
        )
    except TelegramBadRequest as e:
        logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
    await callback.message.edit_text("Заявка закрыта!", reply_markup=keyboard)
    logger.info(f"Заявка №{appeal_id} закрыта пользователем @{callback.from_user.username}")
    await state.clear()

@router.callback_query(F.data.startswith("delegate_appeal_"))
async def delegate_appeal_start(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    admins = await get_admins()
    if not admins:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет доступных сотрудников для делегирования.", reply_markup=keyboard)
        logger.warning(f"Нет сотрудников для делегирования заявки №{appeal_id}")
        return
    inline_keyboard = []
    for admin in admins:
        inline_keyboard.append([
            InlineKeyboardButton(
                text=f"@{admin['username'] or 'ID_' + str(admin['admin_id'])}",
                callback_data=f"delegate_to_{admin['admin_id']}_{appeal_id}"
            )
        ])
    inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await callback.message.edit_text("Выберите сотрудника для делегирования:", reply_markup=keyboard)
    await state.update_data(appeal_id=appeal_id)
    logger.debug(f"Запрос делегирования заявки №{appeal_id} от пользователя @{callback.from_user.username}")

@router.callback_query(F.data.startswith("delegate_to_"))
async def process_delegate(callback: CallbackQuery, state: FSMContext, **data):
    try:
        db_pool = data.get("db_pool")
        if not db_pool:
            logger.error("db_pool отсутствует в data")
            await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]))
            return
        parts = callback.data.split("_")
        new_admin_id = int(parts[2])
        appeal_id = int(parts[3])
        await delegate_appeal(appeal_id, new_admin_id)
        try:
            await callback.message.bot.send_message(
                chat_id=new_admin_id,
                text=f"Вам делегирована заявка №{appeal_id}.\n"
                     f"Просмотрите её для дальнейших действий.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Просмотреть заявку", callback_data=f"view_appeal_{appeal_id}")]
                ])
            )
            logger.info(f"Уведомление о делегировании заявки №{appeal_id} отправлено сотруднику ID {new_admin_id}")
        except TelegramBadRequest as e:
            logger.error(f"Ошибка отправки уведомления сотруднику ID {new_admin_id}: {str(e)}")
            await callback.message.answer(f"Заявка делегирована, но не удалось отправить уведомление сотруднику: {str(e)}")
        await callback.message.edit_text(f"Заявка №{appeal_id} успешно делегирована!")
        logger.info(f"Заявка №{appeal_id} успешно делегирована администратору {new_admin_id}")
        await state.clear()
        await callback.answer()
    except ValueError as e:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(f"Ошибка делегирования заявки №{appeal_id}: {str(e)}")
        await callback.answer()

@router.callback_query(F.data == "open_appeals")
async def show_open_appeals(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    logger.debug(f"Callback open_appeals получен от @{callback.from_user.username} (ID: {callback.from_user.id})")
    admin_id = callback.from_user.id
    appeals = await get_open_appeals(admin_id)
    if not appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет открытых заявок.", reply_markup=keyboard)
        logger.info(f"Нет открытых заявок для сотрудника ID {admin_id}")
        return
    await callback.message.edit_text("Открытые заявки:", reply_markup=get_open_appeals_menu(appeals))
    logger.info(f"Пользователь @{callback.from_user.username} (ID: {admin_id}) просмотрел открытые заявки ({len(appeals)} шт.)")

@router.callback_query(F.data == "my_appeals")
async def show_my_appeals(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    admin_id = callback.from_user.id
    appeals = await get_assigned_appeals(admin_id)
    if not appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("У вас нет закреплённых заявок.", reply_markup=keyboard)
        logger.info(f"У пользователя ID {admin_id} нет закреплённых заявок")
        return
    await callback.message.edit_text("Ваши заявки:", reply_markup=get_my_appeals_menu(appeals))
    logger.info(f"Пользователь @{callback.from_user.username} (ID: {admin_id}) просмотрел свои заявки ({len(appeals)} шт.)")

@router.callback_query(F.data.startswith("view_appeal_"))
async def view_appeal(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.edit_text("Заявка не найдена.")
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    media_files = json.loads(appeal["media_files"]) if appeal["media_files"] else []
    media_group = []
    for media in media_files:
        if media["type"] == "photo" and media.get("file_id"):
            media_group.append(InputMediaPhoto(media=media["file_id"]))
        elif media["type"] in ["video", "video_note"] and media.get("file_id"):
            media_group.append(InputMediaVideo(media=media["file_id"]))
    new_serial_text = f"\nНовый серийник: {appeal.get('new_serial', '')}" if appeal.get('new_serial') else ""
    text = (f"Заявка №{appeal['appeal_id']}:\n"
            f"Серийный номер: {appeal['serial']}\n"
            f"Описание: {appeal['description']}\n"
            f"Статус: {appeal['status']}{new_serial_text}")
    try:
        await callback.message.delete()
        if media_group:
            await callback.message.bot.send_media_group(
                chat_id=callback.from_user.id,
                media=media_group
            )
        await callback.message.bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=get_appeal_actions_menu(appeal_id, appeal['status'])
        )
    except TelegramBadRequest as e:
        logger.error(f"Ошибка отправки медиафайлов для заявки №{appeal_id} пользователю @{callback.from_user.username}: {str(e)}")
        await callback.message.bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=get_appeal_actions_menu(appeal_id, appeal['status'])
        )
    logger.info(f"Пользователь @{callback.from_user.username} просмотрел заявку №{appeal_id}")

@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка доступа к статистике от неадминистратора @{callback.from_user.username}")
        return
    async with db_pool.acquire() as conn:
        status_counts = await conn.fetch("SELECT COUNT(*) as total, status FROM appeals GROUP BY status")
        admin_stats = await conn.fetch("SELECT username, appeals_taken FROM admins")
    if not status_counts and not admin_stats:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет данных по заявкам или сотрудникам.", reply_markup=keyboard)
        logger.info(f"Статистика пуста, запрос от @{callback.from_user.username}")
        return
    response = "Статистика заявок:\n"
    for count in status_counts:
        response += f"{count['status']}: {count['total']}\n"
    response += "\nСтатистика сотрудников:\n"
    for admin in admin_stats:
        response += f"@{admin['username']}: {admin['appeals_taken']} заявок\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text(response, reply_markup=keyboard)
    logger.info(f"Статистика запрошена пользователем @{callback.from_user.username}")

@router.callback_query(F.data == "manage_base")
async def manage_base(callback: CallbackQuery):
    await callback.message.edit_text("Управление базой:", reply_markup=get_base_management_menu())
    logger.info(f"Пользователь @{callback.from_user.username} открыл управление базой")

@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка доступа к админ-панели от неадминистратора @{callback.from_user.username}")
        return
    await callback.message.edit_text("Панель администратора:", reply_markup=get_admin_panel_menu())
    logger.info(f"Пользователь @{callback.from_user.username} открыл админ-панель")

@router.callback_query(F.data == "add_employee")
async def add_employee_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка добавления сотрудника от неадминистратора @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text(
        "Введите Telegram ID и username сотрудника (формат: ID @username). Если username отсутствует, укажите 'Нет'. "
        "Узнать свой Telegram ID можно через @userinfobot, отправив ему команду /start.",
        reply_markup=keyboard
    )
    await state.set_state(AdminResponse.add_employee)
    logger.debug(f"Запрос добавления сотрудника от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.add_employee))
async def process_add_employee(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка добавления сотрудника от неадминистратора @{message.from_user.username}")
        return
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError("Формат: ID @username или ID Нет")
        admin_id = int(parts[0])
        username = parts[1].lstrip("@") if parts[1] != "Нет" else None
        await add_admin(admin_id, username)
        await message.answer(f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен.")
        logger.info(f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError as e:
        await message.answer(str(e))
        logger.error(f"Неверный формат ввода сотрудника {message.text} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
        logger.error(f"Ошибка добавления сотрудника: {str(e)} от @{message.from_user.username}")

@router.callback_query(F.data == "add_channel")
async def add_channel_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка добавления канала от неадминистратора @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите данные канала/группы (формат: @username [topic_id]):", reply_markup=keyboard)
    await state.set_state(AdminResponse.add_channel)
    logger.debug(f"Запрос добавления канала от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.add_channel))
async def process_add_channel(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка добавления канала от неадминистратора @{message.from_user.username}")
        return
    try:
        parts = message.text.split()
        if len(parts) not in [1, 2]:
            raise ValueError
        channel_name = parts[0]
        topic_id = int(parts[1]) if len(parts) == 2 else None
        if not channel_name.startswith("@"):
            raise ValueError
        chat = await message.bot.get_chat(channel_name)
        channel_id = chat.id
        admins = await message.bot.get_chat_administrators(channel_id)
        bot_id = (await message.bot.get_me()).id
        if not any(admin.user.id == bot_id for admin in admins):
            await message.answer("Бот должен быть администратором в группе/канале.")
            logger.error(f"Бот не является администратором в канале {channel_name} при добавлении от @{message.from_user.username}")
            return
        try:
            await message.bot.send_message(chat_id=channel_id, message_thread_id=topic_id, text="Тестовое сообщение")
        except TelegramBadRequest:
            await message.answer("Канал/группа недоступна или topic_id неверный.")
            logger.error(f"Неверный topic_id {topic_id} для канала {channel_name} от @{message.from_user.username}")
            return
        await add_notification_channel(channel_id, channel_name, topic_id)
        await message.answer(f"Канал/группа {channel_name} добавлена для уведомлений.")
        logger.info(f"Канал/группа {channel_name} (ID: {channel_id}, topic_id: {topic_id}) добавлена пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError:
        await message.answer("Неверный формат. Укажите @username и, при необходимости, topic_id.")
        logger.error(f"Неверный формат ввода канала {message.text} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
        logger.error(f"Ошибка добавления канала: {str(e)} от @{message.from_user.username}")

@router.callback_query(F.data == "remove_channel")
async def remove_channel_prompt(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка удаления канала от неадминистратора @{callback.from_user.username}")
        return
    channels = await get_notification_channels()
    if not channels:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет каналов/групп для уведомлений.", reply_markup=keyboard)
        logger.info(f"Нет каналов для удаления, запрос от @{callback.from_user.username}")
        return
    await callback.message.edit_text("Выберите канал/группу для удаления:", reply_markup=get_remove_channel_menu(channels))
    logger.debug(f"Запрос удаления канала от @{callback.from_user.username}")

@router.callback_query(F.data.startswith("remove_channel_"))
async def process_remove_channel(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка удаления канала от неадминистратора @{callback.from_user.username}")
        return
    channel_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        channel_name = await conn.fetchval("SELECT channel_name FROM notification_channels WHERE channel_id = $1", channel_id)
        await conn.execute("DELETE FROM notification_channels WHERE channel_id = $1", channel_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Канал/группа удалена из списка уведомлений.", reply_markup=keyboard)
    logger.info(f"Канал/группа {channel_name} (ID: {channel_id}) удалена пользователем @{callback.from_user.username}")

@router.callback_query(F.data == "edit_channel")
async def edit_channel_prompt(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка редактирования канала от неадминистратора @{callback.from_user.username}")
        return
    channels = await get_notification_channels()
    if not channels:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет каналов/групп для редактирования.", reply_markup=keyboard)
        logger.info(f"Нет каналов для редактирования, запрос от @{callback.from_user.username}")
        return
    await callback.message.edit_text("Выберите канал/группу для редактирования:", reply_markup=get_edit_channel_menu(channels))
    logger.debug(f"Запрос редактирования канала от @{callback.from_user.username}")

@router.callback_query(F.data.startswith("edit_channel_"))
async def process_edit_channel_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка редактирования канала от неадминистратора @{callback.from_user.username}")
        return
    channel_id = int(callback.data.split("_")[-1])
    await state.update_data(channel_id=channel_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите новый topic_id (или оставьте пустым для удаления topic_id):", reply_markup=keyboard)
    await state.set_state(AdminResponse.edit_channel)
    logger.debug(f"Запрос редактирования topic_id для канала ID {channel_id} от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.edit_channel))
async def process_edit_channel(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка редактирования канала от неадминистратора @{message.from_user.username}")
        return
    try:
        topic_id = int(message.text) if message.text.strip() else None
        data_state = await state.get_data()
        channel_id = data_state["channel_id"]
        async with db_pool.acquire() as conn:
            channel_name = await conn.fetchval("SELECT channel_name FROM notification_channels WHERE channel_id = $1", channel_id)
            try:
                await message.bot.send_message(chat_id=channel_id, message_thread_id=topic_id, text="Тестовое сообщение")
            except TelegramBadRequest:
                await message.answer("Неверный topic_id или канал/группа недоступна.")
                logger.error(f"Неверный topic_id {topic_id} для канала {channel_name} от @{message.from_user.username}")
                return
            await conn.execute(
                "UPDATE notification_channels SET topic_id = $1 WHERE channel_id = $2",
                topic_id, channel_id
            )
        await message.answer(f"Канал/группа {channel_name} обновлена.")
        logger.info(f"Канал/группа {channel_name} (ID: {channel_id}) обновлена с topic_id {topic_id} пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError:
        await message.answer("Введите корректный topic_id или оставьте поле пустым.")
        logger.error(f"Неверный формат topic_id {message.text} для канала ID {channel_id} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
        logger.error(f"Ошибка редактирования канала: {str(e)} для канала ID {channel_id} от @{message.from_user.username}")

@router.callback_query(F.data == "list_channels")
async def list_channels(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка просмотра каналов от неадминистратора @{callback.from_user.username}")
        return
    channels = await get_notification_channels()
    if not channels:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет добавленных каналов/групп.", reply_markup=keyboard)
        logger.info(f"Нет каналов для просмотра, запрос от @{callback.from_user.username}")
        return
    response = "Список каналов/групп для уведомлений:\n"
    for channel in channels:
        response += f"{channel['channel_name']}{f'/{channel['topic_id']}' if channel['topic_id'] else ''}\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text(response, reply_markup=keyboard)
    logger.info(f"Список каналов запрошен пользователем @{callback.from_user.username}")

@router.message(F.document)
async def process_import(message: Message, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if message.document.mime_type != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        await message.answer("Отправьте Excel-файл.")
        logger.error(f"Неверный формат файла от @{message.from_user.username}")
        return
    file = await message.bot.get_file(message.document.file_id)
    file_io = await message.bot.download_file(file.file_path)
    result, error = await import_serials(file_io, db_pool)
    if error:
        await message.answer(error)
        logger.error(f"Ошибка импорта от @{message.from_user.username}: {error}")
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        response = (f"Добавлено: {result['added']}\n"
                    f"Пропущено: {result['skipped']}\n"
                    f"Непринятые номера: {', '.join(result['invalid']) if result['invalid'] else 'Нет'}")
        await message.answer(response, reply_markup=keyboard)
        logger.info(f"Импорт завершён пользователем @{message.from_user.username}: {response}")

@router.callback_query(F.data == "import_serials")
async def import_serials_prompt(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Отправьте Excel-файл с серийными номерами (столбец 'Serial'):", reply_markup=keyboard)
    logger.debug(f"Запрос импорта серийников от @{callback.from_user.username}")

@router.callback_query(F.data == "export_serials")
async def export_serials_handler(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    output = await export_serials(db_pool)
    if output is None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет данных для экспорта.", reply_markup=keyboard)
        logger.warning(f"Нет данных для экспорта, запрос от @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.answer_document(
        document=BufferedInputFile(output.getvalue(), filename="serials_export.xlsx"),
        reply_markup=keyboard
    )
    logger.info(f"Экспорт серийников выполнен пользователем @{callback.from_user.username}")

@router.callback_query(F.data == "mark_defect")
async def mark_defect(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите серийный номер устройства:", reply_markup=keyboard)
    await state.set_state(AdminResponse.mark_defect)
    logger.debug(f"Запрос отметки брака от @{callback.from_user.username}")

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
    await state.update_data(serial=serial)
    keyboard = get_defect_status_menu(serial)
    await message.answer("Выберите статус для устройства:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_status)
    logger.debug(f"Пользователь @{message.from_user.username} ввёл серийник {serial} для отметки статуса")

@router.callback_query(F.data.startswith("defect_status_"))
async def process_defect_status(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    parts = callback.data.split("_")
    status = parts[2]
    serial = "_".join(parts[3:])
    data_state = await state.get_data()
    if serial != data_state.get('serial'):
        await callback.message.edit_text("Ошибка: серийный номер не совпадает.")
        logger.error(f"Несовпадение серийного номера {serial} от @{callback.from_user.username}")
        await state.clear()
        return
    if status in ["brak", "vozvrat"]:
        await mark_defect(serial, status.capitalize())
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text(f"Серийный номер {serial} отмечен как {status.capitalize()}.", reply_markup=keyboard)
        logger.info(f"Серийный номер {serial} отмечен как {status.capitalize()} пользователем @{callback.from_user.username}")
        await state.clear()
    elif status == "zamena":
        appeals = await get_replacement_appeals()
        if not appeals:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ])
            await callback.message.edit_text("Нет активных заявок для замены.", reply_markup=keyboard)
            logger.info(f"Нет заявок для замены серийника {serial}")
            await state.clear()
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for appeal in appeals:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"Заявка №{appeal['appeal_id']} ({appeal['serial']})",
                    callback_data=f"select_appeal_{appeal['appeal_id']}_{serial}"
                )
            ])
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
        await callback.message.edit_text("Выберите заявку для замены устройства:", reply_markup=keyboard)
        await state.update_data(serial=serial)
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
    parts = callback.data.split("_")
    appeal_id = int(parts[2])
    serial = "_".join(parts[3:])
    await start_replacement(appeal_id, serial)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text(
        f"Заявка №{appeal_id} переведена в статус 'процесс замены'. Введите новый серийный номер или вернитесь позже:",
        reply_markup=keyboard
    )
    await state.set_state(AdminResponse.new_serial)
    await state.update_data(appeal_id=appeal_id, old_serial=serial)
    logger.info(f"Заявка №{appeal_id} переведена в статус 'процесс замены' для серийника {serial} пользователем @{callback.from_user.username}")
    await callback.answer()

@router.message(StateFilter(AdminResponse.new_serial))
async def process_new_serial(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    new_serial = message.text
    if not validate_serial(new_serial):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Неверный формат серийного номера (A-Za-z0-9, 8–20 символов).", reply_markup=keyboard)
        logger.warning(f"Неверный новый серийный номер {new_serial} от @{message.from_user.username}")
        return
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    old_serial = data_state["old_serial"]
    await complete_replacement(appeal_id, new_serial)
    appeal = await get_appeal(appeal_id)
    try:
        await message.bot.send_message(
            chat_id=appeal["user_id"],
            text=f"Ваше устройство с серийным номером {old_serial} заменено на новое с серийным номером {new_serial}."
        )
        logger.debug(f"Уведомление о замене отправлено пользователю ID {appeal['user_id']} для заявки №{appeal_id}")
    except TelegramBadRequest as e:
        logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await message.answer(f"Замена завершена. Новый серийный номер {new_serial} добавлен.", reply_markup=keyboard)
    logger.info(f"Замена завершена для заявки №{appeal_id}, новый серийник: {new_serial}, пользователь: @{message.from_user.username}")
    await state.clear()

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
        asyncio.create_task(check_overdue(appeal_id, message.bot, hours))
        await state.clear()
    except ValueError:
        await message.answer("Введите число часов.")
        logger.error(f"Неверный формат времени просрочки от @{message.from_user.username}")

@router.callback_query(F.data.startswith("await_specialist_"))
async def await_specialist(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка перевода заявки в статус 'Ожидает специалиста' от неадминистратора @{callback.from_user.username}")
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE appeals SET status = $1 WHERE appeal_id = $2", "awaiting_specialist", appeal_id)
    media_files = json.loads(appeal["media_files"]) if appeal["media_files"] else []
    media_group = []
    for media in media_files:
        if media["type"] == "photo" and media.get("file_id"):
            media_group.append(InputMediaPhoto(media=media["file_id"]))
        elif media["type"] in ["video", "video_note"] and media.get("file_id"):
            media_group.append(InputMediaVideo(media=media["file_id"]))
    text = (f"Ваша заявка №{appeal_id} требует выезда специалиста.\n"
            f"Серийный номер: {appeal['serial']}\n"
            f"Описание: {appeal['description']}\n"
            f"Мы свяжемся с вами для уточнения деталей.")
    try:
        if media_group:
            await callback.message.bot.send_media_group(
                chat_id=appeal["user_id"],
                media=media_group
            )
        await callback.message.bot.send_message(
            chat_id=appeal["user_id"],
            text=text
        )
    except TelegramBadRequest as e:
        logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Заявка переведена в статус 'Ожидает выезда специалиста'.", reply_markup=keyboard)
    logger.info(f"Заявка №{appeal_id} переведена в статус 'Ожидает специалиста' пользователем @{callback.from_user.username}")

async def check_overdue(appeal_id, bot, hours=24):
    await asyncio.sleep(hours * 3600)
    db_pool = await get_db_pool()
    appeal = await get_appeal(appeal_id)
    if appeal["status"] == "in_progress":
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE appeals SET status = $1 WHERE appeal_id = $2", "overdue", appeal_id)
        for main_admin_id in MAIN_ADMIN_IDS:
            await bot.send_message(
                main_admin_id,
                f"Заявка №{appeal_id} просрочена.",
                reply_markup=get_overdue_menu(appeal_id)
            )
        logger.info(f"Заявка №{appeal_id} просрочена")

async def check_delegated_overdue(appeal_id, bot, employee_id):
    await asyncio.sleep(12 * 3600)
    db_pool = await get_db_pool()
    appeal = await get_appeal(appeal_id)
    if appeal["status"] in ["in_progress", "postponed", "replacement_process"] and appeal["admin_id"] == employee_id:
        for main_admin_id in MAIN_ADMIN_IDS:
            await bot.send_message(
                main_admin_id,
                f"Сотрудник ID {employee_id} не ответил на делегированную заявку №{appeal_id} в течение 12 часов.",
                reply_markup=get_overdue_menu(appeal_id)
            )
        logger.info(f"Делегированная заявка №{appeal_id} не обработана сотрудником ID {employee_id}")