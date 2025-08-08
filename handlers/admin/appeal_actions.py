from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_appeal_actions_menu, get_notification_menu, get_response_menu, get_open_appeals_menu, get_my_appeals_menu
from utils.statuses import APPEAL_STATUSES
from database.db import get_appeal, take_appeal, postpone_appeal, save_response, delegate_appeal, get_open_appeals, get_assigned_appeals, get_notification_channels, get_admins
from config import MAIN_ADMIN_IDS
from datetime import datetime
import asyncio
import json
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
import logging

logger = logging.getLogger(__name__)

router = Router()

class AdminResponse(StatesGroup):
    response = State()
    continue_dialogue = State()
    delegate = State()
    open_appeals = State()
    my_appeals = State()
    response_media = State()  # Добавлено для медиа

async def show_my_appeals_page(message: Message, state: FSMContext, appeals: list, page: int, total: int):
    start_idx = page * 10
    end_idx = min(start_idx + 10, len(appeals))
    page_appeals = appeals[start_idx:end_idx]

    if not page_appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Нет назначенных заявок.", reply_markup=keyboard)
        logger.info(f"Нет назначенных заявок для отображения пользователем @{message.from_user.username}")
        return

    keyboard = get_my_appeals_menu(page_appeals, page, total)
    total_pages = (total + 9) // 10 if total > 0 else 1
    response = f"Мои заявки (страница {page + 1} из {total_pages})"
    await message.answer(response, reply_markup=keyboard)
    logger.info(f"Показана страница {page} назначенных заявок пользователю @{message.from_user.username} (ID: {message.from_user.id})")

@router.callback_query(F.data == "process_response")
async def process_response_prompt(callback: CallbackQuery, state: FSMContext, **data):
    appeal_id = int(callback.data.split("_")[-1])
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.delete()
        await callback.message.answer("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    await state.update_data(appeal_id=appeal_id, media_files=[])
    await state.set_state(AdminResponse.response)
    await callback.message.edit_text("Введите ответ для заявки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ]))
    logger.info(f"Запрос ответа для заявки №{appeal_id} от пользователя @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.response))
async def process_response(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    user_id = message.from_user.id
    data_state = await state.get_data()
    appeal_id = data_state.get("appeal_id")
    media_files = data_state.get("media_files", [])
    if message.photo:
        media_files.append({"type": "photo", "file_id": message.photo[-1].file_id})
        await state.update_data(media_files=media_files)
        await message.answer("Фото добавлено. Отправьте ещё медиа или текст ответа.")
        return
    elif message.video:
        media_files.append({"type": "video", "file_id": message.video.file_id})
        await state.update_data(media_files=media_files)
        await message.answer("Видео добавлено. Отправьте ещё медиа или текст ответа.")
        return
    elif message.video_note:
        media_files.append({"type": "video_note", "file_id": message.video_note.file_id})
        await state.update_data(media_files=media_files)
        await message.answer("Кружок добавлен. Отправьте ещё медиа или текст ответа.")
        return
    elif message.text:
        response = message.text
        await save_response(appeal_id, response, json.dumps(media_files))
        await message.answer("Ответ отправлен.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ]))
        logger.info(f"Ответ по заявке №{appeal_id} отправлен пользователем @{message.from_user.username}")
        await state.clear()
    else:
        await message.answer("Отправьте текст или медиафайл.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ]))
        logger.warning(f"Некорректный ввод для ответа на заявку №{appeal_id} от пользователя @{message.from_user.username}")

@router.callback_query(F.data.startswith("continue_dialogue_"))
async def continue_dialogue_prompt(callback: CallbackQuery, state: FSMContext, **data):
    appeal_id = int(callback.data.split("_")[-1])
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.delete()
        await callback.message.answer("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    await state.update_data(appeal_id=appeal_id, media_files=[])
    await state.set_state(AdminResponse.continue_dialogue)
    await callback.message.edit_text("Введите продолжение диалога:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ]))
    logger.info(f"Запрос продолжения диалога для заявки №{appeal_id} от пользователя @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.continue_dialogue))
async def process_continue_dialogue(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    user_id = message.from_user.id
    data_state = await state.get_data()
    appeal_id = data_state.get("appeal_id")
    media_files = data_state.get("media_files", [])
    if message.photo:
        media_files.append({"type": "photo", "file_id": message.photo[-1].file_id})
        await state.update_data(media_files=media_files)
        await message.answer("Фото добавлено. Отправьте ещё медиа или текст ответа.")
        return
    elif message.video:
        media_files.append({"type": "video", "file_id": message.video.file_id})
        await state.update_data(media_files=media_files)
        await message.answer("Видео добавлено. Отправьте ещё медиа или текст ответа.")
        return
    elif message.video_note:
        media_files.append({"type": "video_note", "file_id": message.video_note.file_id})
        await state.update_data(media_files=media_files)
        await message.answer("Кружок добавлен. Отправьте ещё медиа или текст ответа.")
        return
    elif message.text:
        response = message.text
        await save_response(appeal_id, f"[Медиа] {response}", json.dumps(media_files))
        await message.answer("Ответ отправлен.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ]))
        logger.info(f"Продолжение диалога для заявки №{appeal_id} отправлено пользователем @{message.from_user.username}")
        await state.clear()
    else:
        await message.answer("Отправьте текст или медиафайл.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ]))
        logger.warning(f"Некорректный ввод для продолжения диалога на заявку №{appeal_id} от пользователя @{message.from_user.username}")

@router.callback_query(F.data == "my_appeals")
async def my_appeals_prompt(callback: CallbackQuery, state: FSMContext, **data):
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
        logger.warning(f"Попытка доступа к назначенным заявкам от неадминистратора @{callback.from_user.username} (ID: {user_id})")
        return
    appeals, total = await get_assigned_appeals(user_id, page=0)
    await state.update_data(appeals=appeals, total=total, page=0)
    await callback.message.delete()
    await show_my_appeals_page(callback.message, state, appeals, 0, total)
    await callback.answer()

@router.callback_query(F.data.startswith("my_appeals_page_"))
async def navigate_my_appeals_page(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    page = int(callback.data.split("_")[-1])
    data_state = await state.get_data()
    appeals = data_state.get('appeals')
    total = data_state.get('total')
    if not appeals or total is None:
        appeals, total = await get_assigned_appeals(callback.from_user.id, page=page)
        await state.update_data(appeals=appeals, total=total)
    await callback.message.delete()
    await show_my_appeals_page(callback.message, state, appeals, page, total)
    await state.update_data(page=page)
    await callback.answer()
    logger.info(f"Показана страница {page} назначенных заявок пользователю @{callback.from_user.username} (ID: {callback.from_user.id})")

async def show_open_appeals_page(message: Message, state: FSMContext, appeals: list, page: int, total: int):
    start_idx = page * 10
    end_idx = min(start_idx + 10, len(appeals))
    page_appeals = appeals[start_idx:end_idx]

    if not page_appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Нет открытых заявок со статусом 'Новая'.", reply_markup=keyboard)
        logger.info(f"Нет открытых заявок для отображения пользователем @{message.from_user.username}")
        return

    keyboard = get_open_appeals_menu(page_appeals, page, total)
    total_pages = (total + 9) // 10 if total > 0 else 1  # Исправлено: учитываем total > 0
    response = f"Открытые заявки (страница {page + 1} из {total_pages})"
    await message.answer(response, reply_markup=keyboard)
    logger.info(
        f"Показана страница {page} открытых заявок пользователю @{message.from_user.username} (ID: {message.from_user.id})")

@router.callback_query(F.data == "open_appeals")
async def open_appeals_prompt(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.",
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
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
        logger.warning(
            f"Попытка доступа к открытым заявкам от неадминистратора @{callback.from_user.username} (ID: {user_id})")
        return
    appeals, total = await get_open_appeals(page=0)
    await state.update_data(appeals=appeals, total=total, page=0)
    await callback.message.delete()
    await show_open_appeals_page(callback.message, state, appeals, 0, total)
    await callback.answer()

@router.callback_query(F.data.startswith("open_appeals_page_"))
async def navigate_open_appeals_page(callback: CallbackQuery, state: FSMContext, **data):
    page = int(callback.data.split("_")[-1])
    data_state = await state.get_data()
    appeals = data_state.get('appeals')
    total = data_state.get('total')
    if not appeals or total is None:
        db_pool = data.get("db_pool")
        if not db_pool:
            logger.error("db_pool отсутствует в data")
            await callback.message.answer("Ошибка сервера. Попробуйте снова.",
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                              [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                          ]))
            return
        appeals, total = await get_open_appeals(page=page)
        await state.update_data(appeals=appeals, total=total)
    await callback.message.delete()
    await show_open_appeals_page(callback.message, state, appeals, page, total)
    await state.update_data(page=page)
    await callback.answer()
    logger.info(
        f"Показана страница {page} открытых заявок пользователю @{callback.from_user.username} (ID: {callback.from_user.id})")

@router.callback_query(F.data.startswith("view_appeal_"))
async def view_appeal(callback: CallbackQuery, **data):
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.delete()
        await callback.message.answer("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    media_files = json.loads(appeal['media_files'] or "[]")
    created_time = appeal['created_time']
    if created_time:
        try:
            created_time_dt = datetime.strptime(created_time, "%Y-%m-%dT%H:%M")
            created_time = created_time_dt.strftime("%d.%m.%Y %H:%M")
        except Exception as e:
            logger.error(f"Ошибка форматирования created_time: {e}")
    taken_time = appeal['taken_time']
    if taken_time:
        try:
            taken_time_dt = datetime.strptime(taken_time, "%Y-%m-%dT%H:%M")
            taken_time = taken_time_dt.strftime("%d.%m.%Y %H:%M")
        except Exception as e:
            logger.error(f"Ошибка форматирования taken_time: {e}")
    new_serial_text = f"\nНовый серийник: {appeal.get('new_serial', '')}" if appeal.get('new_serial') else ""
    response = (f"Заявка №{appeal['appeal_id']}:\n"
                f"Серийный номер: {appeal['serial']}\n"
                f"Дата создания: {created_time}\n"
                f"Дата взятия в работу: {taken_time or 'Не взята'}\n"
                f"Статус: {APPEAL_STATUSES.get(appeal['status'], appeal['status'])}\n"
                f"Описание: {appeal['description']}\n"
                f"Ответ: {appeal['response'] or 'Нет ответа'}{new_serial_text}")
    media_count = len(media_files)
    keyboard = get_appeal_actions_menu(appeal_id, appeal['status']) if appeal['status'] in ['new', 'in_progress', 'postponed', 'overdue', 'replacement_process', 'awaiting_specialist'] else get_response_menu(appeal_id)
    if media_count > 0:
        keyboard.inline_keyboard.insert(0, [InlineKeyboardButton(text=f"📸 Медиа ({media_count})", callback_data=f"view_media_{appeal_id}")])
    await callback.message.delete()
    await callback.message.answer(response, reply_markup=keyboard)
    logger.info(f"Заявка №{appeal_id} просмотрена пользователем @{callback.from_user.username}")

@router.callback_query(F.data.startswith("take_appeal_"))
async def take_appeal_action(callback: CallbackQuery, **data):
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
        await callback.message.delete()
        await callback.message.answer("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    if appeal['status'] != 'new':
        await callback.message.delete()
        await callback.message.answer("Заявка уже взята в работу.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Попытка взять заявку №{appeal_id} со статусом {appeal['status']} пользователем @{callback.from_user.username}")
        return
    async with db_pool.acquire() as conn:
        is_employee = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", callback.from_user.id)
    if callback.from_user.id not in MAIN_ADMIN_IDS and not is_employee:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка взять заявку №{appeal_id} от неадминистратора @{callback.from_user.username}")
        return
    await take_appeal(appeal_id, callback.from_user.id, callback.from_user.username)
    await callback.message.delete()
    await callback.message.answer(f"Заявка №{appeal_id} взята в работу.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ]))
    channels = await get_notification_channels()
    for channel in channels:
        try:
            await callback.message.bot.send_message(
                chat_id=channel['channel_id'],
                message_thread_id=channel['topic_id'],
                text=f"Заявка №{appeal_id} взята в работу @{callback.from_user.username}"
            )  # Убрана кнопка "Взять в работу"
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.error(f"Ошибка отправки уведомления в канал {channel['channel_name']}: {str(e)}")
    logger.info(f"Заявка №{appeal_id} взята в работу пользователем @{callback.from_user.username}")

@router.callback_query(F.data.startswith("reply_appeal_"))
async def reply_appeal_prompt(callback: CallbackQuery, state: FSMContext, **data):
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
        await callback.message.delete()
        await callback.message.answer("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    async with db_pool.acquire() as conn:
        is_employee = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", callback.from_user.id)
    if callback.from_user.id not in MAIN_ADMIN_IDS and not is_employee:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка ответа на заявку №{appeal_id} от неадминистратора @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await callback.message.edit_text("Введите ваш ответ:", reply_markup=keyboard)
    await state.set_state(AdminResponse.response)
    await state.update_data(appeal_id=appeal_id)
    logger.debug(f"Запрос ответа на заявку №{appeal_id} от @{callback.from_user.username}")



@router.callback_query(F.data.startswith("add_response_media_"))
async def add_response_media_prompt(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data=f"done_response_media_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await callback.message.edit_text("Прикрепите фото/видео (до 10, или нажмите 'Готово'):", reply_markup=keyboard)
    await state.set_state(AdminResponse.response_media)
    await state.update_data(appeal_id=appeal_id, media_files=[])
    logger.debug(f"Запрос добавления медиа для ответа на заявку №{appeal_id} от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.response_media))
async def process_response_media(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    data_state = await state.get_data()
    appeal_id = data_state.get("appeal_id")
    media_files = data_state.get("media_files", [])

    if len(media_files) >= 10:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data=f"done_response_media_{appeal_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer("Достигнуто максимальное количество медиа (10). Нажмите 'Готово'.", reply_markup=keyboard)
        logger.warning(
            f"Достигнуто максимальное количество медиа для ответа на заявку №{appeal_id} от @{message.from_user.username}")
        return

    is_valid, media = validate_media(message)
    if is_valid:
        file_id = media[0]['file_id']
        file = await message.bot.get_file(file_id)
        file_path = file.file_path
        full_link = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        media[0]['file_id'] = full_link
        media_files.append(media[0])
        await state.update_data(media_files=media_files)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data=f"done_response_media_{appeal_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer(f"Медиа добавлено ({len(media_files)}/10). Приложите ещё или нажмите 'Готово':",
                             reply_markup=keyboard)
        logger.debug(
            f"Медиа ({media[0]['type']}) добавлено для ответа на заявку №{appeal_id} от @{message.from_user.username}: {full_link}")
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data=f"done_response_media_{appeal_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ])
        await message.answer("Неподдерживаемый формат. Приложите фото (png/jpeg) или видео (mp4).",
                             reply_markup=keyboard)
        logger.warning(
            f"Неподдерживаемый формат медиа для ответа на заявку №{appeal_id} от @{message.from_user.username}")

@router.callback_query(F.data.startswith("done_response_media_"))
async def done_response_media(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.",
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                             [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                         ]))
        return
    data_state = await state.get_data()
    appeal_id = data_state.get("appeal_id")
    media_files = data_state.get("media_files", [])

    async with db_pool.acquire() as conn:
        appeal = await conn.fetchrow("SELECT response, user_id, media_files FROM appeals WHERE appeal_id = $1",
                                     appeal_id)
        existing_response = appeal['response'] or ""
        existing_media = json.loads(appeal['media_files'] or "[]")
        response_lines = existing_response.split('\n') if existing_response else []

        for _ in media_files:
            response_lines.append("[Медиа]")

        new_response = '\n'.join(response_lines)
        existing_media.extend(media_files)

        await save_response(appeal_id, new_response)
        await conn.execute(
            "UPDATE appeals SET media_files = $1 WHERE appeal_id = $2",
            json.dumps(existing_media), appeal_id
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Продолжить переписку", callback_data=f"continue_dialogue_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Медиа сохранены. Продолжить переписку или вернуться в главное меню?",
                                     reply_markup=keyboard)
    try:
        user_id = appeal['user_id']
        await callback.message.bot.send_message(
            chat_id=user_id,
            text=f"Вашей заявке №{appeal_id} добавлены медиафайлы",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Просмотреть заявку", callback_data=f"view_appeal_user_{appeal_id}")]
            ])
        )
        for media in media_files:
            if media["type"] == "photo":
                await callback.message.bot.send_photo(chat_id=user_id, photo=media["file_id"])
            elif media["type"] in ["video", "video_note"]:
                await callback.message.bot.send_video(chat_id=user_id, video=media["file_id"])
        logger.info(f"Уведомление о медиа для заявки №{appeal_id} отправлено пользователю ID {user_id}")
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.error(f"Ошибка отправки уведомления пользователю ID {user_id} для заявки №{appeal_id}: {str(e)}")
    logger.info(f"Медиа для ответа на заявку №{appeal_id} сохранены пользователем @{callback.from_user.username}")
    await state.clear()



@router.callback_query(F.data.startswith("delegate_appeal_"))
async def delegate_appeal_prompt(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.",
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                             [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                         ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    admins = await get_admins()
    if not admins:
        await callback.message.delete()
        await callback.message.answer("Сотрудники не найдены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(
            f"Сотрудники не найдены для делегирования заявки №{appeal_id} пользователем @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for admin in admins:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"@{admin['username']}",
                callback_data=f"assign_to_{admin['admin_id']}_{appeal_id}"
            )
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")])
    await callback.message.edit_text("Выберите сотрудника для делегирования:", reply_markup=keyboard)
    logger.debug(f"Запрос делегирования заявки №{appeal_id} от @{callback.from_user.username}")

@router.callback_query(F.data.startswith("assign_to_"))
async def assign_appeal(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    parts = callback.data.split("_")
    admin_id = int(parts[2])
    appeal_id = int(parts[3])
    async with db_pool.acquire() as conn:
        new_admin_username = await conn.fetchval("SELECT username FROM admins WHERE admin_id = $1", admin_id) or "unknown"
    await delegate_appeal(appeal_id, admin_id, new_admin_username)
    await callback.message.delete()
    await callback.message.answer(f"Заявка №{appeal_id} делегирована сотруднику @{new_admin_username}.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ]))
    try:
        await callback.message.bot.send_message(
            chat_id=admin_id,
            text=f"Вам делегирована заявка №{appeal_id}.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Просмотреть заявку", callback_data=f"view_appeal_{appeal_id}")]
            ])
        )
        logger.info(f"Уведомление о делегировании заявки №{appeal_id} отправлено администратору ID {admin_id}")
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.error(f"Ошибка отправки уведомления администратору ID {admin_id} для заявки №{appeal_id}: {str(e)}")
    logger.info(f"Заявка №{appeal_id} делегирована сотруднику ID {admin_id} пользователем @{callback.from_user.username}")
    await callback.answer()

@router.callback_query(F.data.startswith("await_specialist_"))
async def await_specialist(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.",
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                             [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                         ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.delete()
        await callback.message.answer("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE appeals SET status = 'awaiting_specialist' WHERE appeal_id = $1",
            appeal_id
        )
    await callback.message.delete()
    await callback.message.answer(f"Заявка №{appeal_id} помечена как 'Требуется выезд'.",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                      [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                  ]))
    channels = await get_notification_channels()
    for channel in channels:
        try:
            await callback.message.bot.send_message(
                chat_id=channel['channel_id'],
                message_thread_id=channel['topic_id'],
                text=f"Заявка №{appeal_id} помечена как 'Требуется выезд'.",
                reply_markup=get_notification_menu(appeal_id)
            )
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.error(f"Ошибка отправки уведомления в канал {channel['channel_name']}: {str(e)}")
    logger.info(f"Заявка №{appeal_id} помечена как 'Требуется выезд' пользователем @{callback.from_user.username}")

@router.callback_query(F.data.startswith("view_media_"))
async def view_media(callback: CallbackQuery):
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.delete()
        await callback.message.answer("Заявка не найдена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}")
        return
    media_files = json.loads(appeal['media_files'] or "[]")
    if not media_files:
        await callback.message.delete()
        await callback.message.answer("Медиафайлы отсутствуют.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
        ]))
        logger.info(f"Медиафайлы отсутствуют для заявки №{appeal_id}")
        return
    await callback.message.delete()
    for media in media_files:
        try:
            if media.get("file_id"):
                if media["type"] == "photo":
                    await callback.message.bot.send_photo(
                        chat_id=callback.from_user.id,
                        photo=media["file_id"]
                    )
                elif media["type"] in ["video", "video_note"]:
                    await callback.message.bot.send_video(
                        chat_id=callback.from_user.id,
                        video=media["file_id"]
                    )
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.error(
                f"Ошибка отправки медиа (тип: {media['type']}, file_id: {media.get('file_id')}) для заявки №{appeal_id}: {str(e)}")
    await callback.message.answer("Медиафайлы отображены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ]))
    logger.info(f"Медиафайлы для заявки №{appeal_id} отображены для @{callback.from_user.username}")