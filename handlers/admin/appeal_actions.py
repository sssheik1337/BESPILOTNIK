from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_appeal_actions_menu, get_notification_menu, get_response_menu, get_open_appeals_menu, get_my_appeals_menu
from utils.statuses import APPEAL_STATUSES
from database.db import get_appeal, take_appeal, postpone_appeal, save_response, close_appeal as db_close_appeal, delegate_appeal, get_open_appeals, get_assigned_appeals, get_notification_channels, get_admins
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
    continue_dialogue = State()
    delegate = State()

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
            channels = await get_notification_channels()
            is_channel = any(callback.message.chat.id == channel["channel_id"] for channel in channels)
            if is_channel:
                # В канале отправляем сообщение без клавиатуры
                await callback.message.edit_text(
                    f"Заявка №{appeal_id} уже взята в работу или имеет другой статус.",
                    reply_markup=None
                )
            else:
                # В личной переписке добавляем кнопку "Назад"
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
                    await callback.message.edit_text(channel_text, reply_markup=None)  # Без клавиатуры в канале
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
        from .overdue_checks import check_overdue
        asyncio.create_task(check_overdue(appeal_id, callback.message.bot))
    except Exception as e:
        logger.error(f"Ошибка в take_appeal_callback: {str(e)}")
        is_channel = any(callback.message.chat.id == channel["channel_id"] for channel in await get_notification_channels())
        if is_channel:
            await callback.message.edit_text("Ошибка при взятии заявки. Попробуйте позже.", reply_markup=None)
        else:
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data=f"done_response_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await callback.message.edit_text(
        "Введите ответ по решению проблемы (или нажмите 'Готово' для завершения):",
        reply_markup=keyboard
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
    response = message.text.strip() if message.text else None
    if response:
        existing_response = appeal['response'] or ""
        new_response = f"{existing_response}\n[Администратор] {response}" if existing_response else f"[Администратор] {response}"
        await save_response(appeal_id, new_response)
        try:
            await message.bot.send_message(
                chat_id=appeal["user_id"],
                text=f"Ответ по заявке №{appeal_id}:\n{response}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_appeal_{appeal_id}")]
                ])
            )
            logger.debug(f"Уведомление отправлено пользователю ID {appeal['user_id']} для заявки №{appeal_id}")
        except TelegramBadRequest as e:
            logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Закрыть заявку", callback_data=f"close_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="💬 Продолжить диалог", callback_data=f"continue_dialogue_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await message.answer("Ответ сохранён. Закройте заявку, продолжите диалог или вернитесь в меню:", reply_markup=keyboard)
    await state.clear()
    logger.info(f"Ответ для заявки №{appeal_id} сохранён пользователем @{message.from_user.username}")

@router.callback_query(F.data.startswith("done_response_"))
async def done_response(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Закрыть заявку", callback_data=f"close_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="💬 Продолжить диалог", callback_data=f"continue_dialogue_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await callback.message.edit_text("Ответ не введён. Закройте заявку, продолжите диалог или вернитесь в меню:", reply_markup=keyboard)
    await state.clear()
    logger.info(f"Завершение ввода ответа без текста для заявки №{appeal_id} пользователем @{callback.from_user.username}")
    await callback.answer()

@router.callback_query(F.data.startswith("continue_dialogue_"))
async def continue_dialogue(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data=f"done_dialogue_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await callback.message.edit_text(
        "Введите дополнительный ответ для пользователя (или нажмите 'Готово' для завершения):",
        reply_markup=keyboard
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
    response = message.text.strip() if message.text else None
    if response:
        existing_response = appeal['response'] or ""
        new_response = f"{existing_response}\n[Администратор] {response}" if existing_response else f"[Администратор] {response}"
        await save_response(appeal_id, new_response)
        try:
            await message.bot.send_message(
                chat_id=appeal["user_id"],
                text=f"Новый ответ по заявке №{appeal_id}:\n{response}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_appeal_{appeal_id}")]
                ])
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

@router.callback_query(F.data.startswith("done_dialogue_"))
async def done_dialogue(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Закрыть заявку", callback_data=f"close_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="💬 Продолжить диалог", callback_data=f"continue_dialogue_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await callback.message.edit_text("Ответ не введён. Закройте заявку, продолжите диалог или вернитесь в меню:", reply_markup=keyboard)
    await state.clear()
    logger.info(f"Завершение диалога без текста для заявки №{appeal_id} пользователем @{callback.from_user.username}")
    await callback.answer()

@router.callback_query(F.data.startswith("close_appeal_"))
async def handle_close_appeal(callback: CallbackQuery, state: FSMContext, **data):
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
    await db_close_appeal(appeal_id)  # Вызов функции из db.py с алиасом
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
        from .overdue_checks import check_delegated_overdue
        asyncio.create_task(check_delegated_overdue(appeal_id, callback.message.bot, new_admin_id))
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
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Заявка не найдена.", reply_markup=keyboard)
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
    response_text = f"\nДиалог:\n{appeal['response']}" if appeal['response'] else ""
    text = (f"Заявка №{appeal['appeal_id']}:\n"
            f"Заявитель: @{appeal['username']}\n"
            f"Серийный номер: {appeal['serial']}\n"
            f"Описание: {appeal['description']}\n"
            f"Статус: {APPEAL_STATUSES.get(appeal['status'], appeal['status'])}\n"
            f"Дата создания: {datetime.strptime(appeal['created_time'], '%Y-%m-%dT%H:%M').strftime('%Y-%m-%d %H:%M')}{new_serial_text}{response_text}")
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
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка перевода заявки в статус 'Ожидает специалиста' от неадминистратора @{callback.from_user.username}")
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

    # Добавляем клавиатуру для пользователя
    user_keyboard = InlineKeyboardMarkup(inline_keyboard=[
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
            reply_markup=user_keyboard  # Привязываем клавиатуру здесь
        )
    except TelegramBadRequest as e:
        logger.error(
            f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")

    # Клавиатура для администратора
    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Заявка переведена в статус 'Ожидает выезда специалиста'.",
                                     reply_markup=admin_keyboard)
    logger.info(
        f"Заявка №{appeal_id} переведена в статус 'Ожидает специалиста' пользователем @{callback.from_user.username}")