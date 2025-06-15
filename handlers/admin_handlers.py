from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, \
    InlineKeyboardButton, InputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_admin_menu, get_base_management_menu, get_admin_panel_menu, get_overdue_menu, \
    get_open_appeals_menu, get_my_appeals_menu, get_remove_channel_menu, get_edit_channel_menu, get_appeal_actions_menu, \
    get_notification_menu, get_response_menu
from database.models import Database
from utils.excel_utils import import_serials, export_serials
from config import MAIN_ADMIN_IDS
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


@router.callback_query(F.data.startswith("take_appeal_"))
async def take_appeal(callback: CallbackQuery, state: FSMContext):
    db = Database()
    await db.connect()
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await db.get_appeal(appeal_id)

    # Проверка статуса заявки
    if appeal['status'] not in ["new", "postponed", "overdue"]:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text(
            f"Заявка №{appeal_id} уже взята в работу или имеет другой статус.",
            reply_markup=keyboard
        )
        logger.info(
            f"Попытка повторного взятия заявки №{appeal_id} пользователем @{callback.from_user.username} (ID: {callback.from_user.id})")
        return

    admin_id = callback.from_user.id
    await db.take_appeal(appeal_id, admin_id)
    # Повторно получаем заявку для актуального статуса
    appeal = await db.get_appeal(appeal_id)
    await callback.message.edit_text(
        f"Обращение №{appeal_id} взято в работу @{callback.from_user.username}\n\n"
        f"Серийный номер: {appeal['serial']}\n"
        f"Описание: {appeal['description']}",
        reply_markup=get_appeal_actions_menu(appeal_id, appeal['status'])
    )
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
    except TelegramBadRequest as e:
        logger.error(
            f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
    logger.info(f"Заявка №{appeal_id} взята в работу пользователем @{callback.from_user.username} (ID: {admin_id})")
    asyncio.create_task(check_overdue(appeal_id, callback.message.bot))


@router.callback_query(F.data.startswith("postpone_appeal_"))
async def postpone_appeal_notification(callback: CallbackQuery):
    db = Database()
    await db.connect()
    appeal_id = int(callback.data.split("_")[-1])
    await db.postpone_appeal(appeal_id)
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
async def process_response(message: Message, state: FSMContext):
    data = await state.get_data()
    appeal_id = data["appeal_id"]
    db = Database()
    await db.connect()
    appeal = await db.get_appeal(appeal_id)
    await db.save_response(appeal_id, message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Закрыть заявку", callback_data=f"close_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])
    await message.answer("Ответ сохранён. Закройте заявку или вернитесь в меню:", reply_markup=keyboard)
    await state.clear()
    logger.info(f"Ответ для заявки №{appeal_id} сохранён пользователем @{message.from_user.username}")


@router.callback_query(F.data.startswith("close_appeal_"))
async def close_appeal(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    db = Database()
    await db.connect()
    appeal = await db.get_appeal(appeal_id)
    logger.debug(f"Извлечён ответ для заявки №{appeal_id}: {appeal['response']}")
    await db.close_appeal(appeal_id)
    media_files = json.loads(appeal["media_files"]) if appeal["media_files"] else []
    media_group = []
    for media in media_files:
        if media["type"] == "photo" and media.get("file_id"):
            media_group.append(InputMediaPhoto(media=media["file_id"]))
        elif media["type"] in ["video", "video_note"] and media.get("file_id"):
            media_group.append(InputMediaVideo(media=media["file_id"]))
    response_text = appeal['response'] if appeal['response'] is not None else "Ответ отсутствует"
    text = (f"Ваша заявка №{appeal_id} закрыта.\n"
            f"Серийный номер: {appeal['serial']}\n"
            f"Описание: {appeal['description']}\n"
            f"Ответ: {response_text}")
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
        logger.error(
            f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
    await callback.message.edit_text("Заявка закрыта!", reply_markup=keyboard)
    logger.info(f"Заявка №{appeal_id} закрыта пользователем @{callback.from_user.username}")
    await state.clear()


@router.callback_query(F.data.startswith("delegate_appeal_"))
async def delegate_appeal(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    await callback.message.edit_text("Введите Telegram ID сотрудника:")
    await state.set_state(AdminResponse.delegate)
    await state.update_data(appeal_id=appeal_id)
    logger.debug(f"Запрос делегирования заявки №{appeal_id} от пользователя @{callback.from_user.username}")


@router.message(StateFilter(AdminResponse.delegate))
async def process_delegate(message: Message, state: FSMContext):
    try:
        new_admin_id = int(message.text.strip())
        data = await state.get_data()
        appeal_id = data["appeal_id"]
        db = Database()
        await db.connect()
        appeal = await db.get_appeal(appeal_id)
        async with db.conn.cursor() as cursor:
            await cursor.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (new_admin_id,))
            if not await cursor.fetchone():
                raise ValueError(f"Сотрудник с ID {new_admin_id} не найден в базе")
        await db.delegate_appeal(appeal_id, new_admin_id)
        await message.answer("Заявка делегирована!")
        for main_admin_id in MAIN_ADMIN_IDS:
            await message.bot.send_message(
                main_admin_id,
                f"Заявка №{appeal_id} делегирована на сотрудника ID {new_admin_id}"
            )
        media_files = json.loads(appeal["media_files"]) if appeal["media_files"] else []
        media_group = []
        for media in media_files:
            if media["type"] == "photo" and media.get("file_id"):
                media_group.append(InputMediaPhoto(media=media["file_id"]))
            elif media["type"] in ["video", "video_note"] and media.get("file_id"):
                media_group.append(InputMediaVideo(media=media["file_id"]))
        text = (f"Вам делегирована заявка №{appeal_id}:\n"
                f"Серийный номер: {appeal['serial']}\n"
                f"Описание: {appeal['description']}")
        try:
            if media_group:
                await message.bot.send_media_group(
                    chat_id=new_admin_id,
                    media=media_group
                )
            await message.bot.send_message(
                chat_id=new_admin_id,
                text=text,
                reply_markup=get_appeal_actions_menu(appeal_id, appeal['status'])
            )
            logger.info(f"Уведомление о делегировании заявки №{appeal_id} отправлено ID {new_admin_id}")
        except TelegramBadRequest as e:
            logger.error(f"Ошибка отправки уведомления сотруднику ID {new_admin_id} для заявки №{appeal_id}: {str(e)}")
        logger.info(
            f"Заявка №{appeal_id} делегирована на сотрудника ID {new_admin_id} пользователем @{message.from_user.username}")
        asyncio.create_task(check_delegated_overdue(appeal_id, message.bot, new_admin_id))
        await state.clear()
    except ValueError as e:
        await message.answer(str(e))
        logger.error(f"Ошибка делегирования заявки №{appeal_id}: {str(e)} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
        logger.error(f"Ошибка делегирования заявки №{appeal_id}: {str(e)} от @{message.from_user.username}")


@router.callback_query(F.data == "open_appeals")
async def show_open_appeals(callback: CallbackQuery):
    logger.debug(f"Callback open_appeals получен от @{callback.from_user.username} (ID: {callback.from_user.id})")
    db = Database()
    await db.connect()
    admin_id = callback.from_user.id
    appeals = await db.get_open_appeals(admin_id)
    if not appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет открытых заявок.", reply_markup=keyboard)
        logger.info(f"Нет открытых заявок для сотрудника ID {admin_id}")
        return
    await callback.message.edit_text("Открытые заявки:", reply_markup=get_open_appeals_menu(appeals))
    logger.info(
        f"Пользователь @{callback.from_user.username} (ID: {admin_id}) просмотрел открытые заявки ({len(appeals)} шт.)")


@router.callback_query(F.data == "my_appeals")
async def show_my_appeals(callback: CallbackQuery):
    db = Database()
    await db.connect()
    admin_id = callback.from_user.id
    appeals = await db.get_assigned_appeals(admin_id)
    if not appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("У вас нет закреплённых заявок.", reply_markup=keyboard)
        logger.info(f"У пользователя ID {admin_id} нет закреплённых заявок")
        return
    await callback.message.edit_text("Ваши заявки:", reply_markup=get_my_appeals_menu(appeals))
    logger.info(
        f"Пользователь @{callback.from_user.username} (ID: {admin_id}) просмотрел свои заявки ({len(appeals)} шт.)")


@router.callback_query(F.data.startswith("view_appeal_"))
async def view_appeal(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    db = Database()
    await db.connect()
    appeal = await db.get_appeal(appeal_id)
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
    text = (f"Заявка №{appeal['appeal_id']}:\n"
            f"Серийный номер: {appeal['serial']}\n"
            f"Описание: {appeal['description']}\n"
            f"Статус: {appeal['status']}")
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
        logger.error(
            f"Ошибка отправки медиафайлов для заявки №{appeal_id} пользователю @{callback.from_user.username}: {str(e)}")
        await callback.message.bot.send_message(
            chat_id=callback.from_user.id,
            text=text,
            reply_markup=get_appeal_actions_menu(appeal_id, appeal['status'])
        )
    logger.info(f"Пользователь @{callback.from_user.username} просмотрел заявку №{appeal_id}")


@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка доступа к статистике от неадминистратора @{callback.from_user.username}")
        return
    db = Database()
    await db.connect()
    async with db.conn.cursor() as cursor:
        await cursor.execute("SELECT COUNT(*) as total, status FROM appeals GROUP BY status")
        status_counts = await cursor.fetchall()
        await cursor.execute("SELECT username, appeals_taken FROM admins")
        admin_stats = await cursor.fetchall()
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
async def process_add_employee(message: Message, state: FSMContext):
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
        db = Database()
        await db.connect()
        await db.add_admin(admin_id, username)
        await message.answer(f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен.")
        logger.info(
            f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен пользователем @{message.from_user.username}")
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
    await callback.message.edit_text("Введите данные канала/группы (формат: @username [topic_id]):",
                                     reply_markup=keyboard)
    await state.set_state(AdminResponse.add_channel)
    logger.debug(f"Запрос добавления канала от @{callback.from_user.username}")


@router.message(StateFilter(AdminResponse.add_channel))
async def process_add_channel(message: Message, state: FSMContext):
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
            logger.error(
                f"Бот не является администратором в канале {channel_name} при добавлении от @{message.from_user.username}")
            return
        try:
            await message.bot.send_message(chat_id=channel_id, message_thread_id=topic_id, text="Тестовое сообщение")
        except TelegramBadRequest:
            await message.answer("Канал/группа недоступна или topic_id неверный.")
            logger.error(f"Неверный topic_id {topic_id} для канала {channel_name} от @{message.from_user.username}")
            return
        db = Database()
        await db.connect()
        await db.add_notification_channel(channel_id, channel_name, topic_id)
        await message.answer(f"Канал/группа {channel_name} добавлена для уведомлений.")
        logger.info(
            f"Канал/группа {channel_name} (ID: {channel_id}, topic_id: {topic_id}) добавлена пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError:
        await message.answer("Неверный формат. Укажите @username и, при необходимости, topic_id.")
        logger.error(f"Неверный формат ввода канала {message.text} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
        logger.error(f"Ошибка добавления канала: {str(e)} от @{message.from_user.username}")


@router.callback_query(F.data == "remove_channel")
async def remove_channel_prompt(callback: CallbackQuery):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка удаления канала от неадминистратора @{callback.from_user.username}")
        return
    db = Database()
    await db.connect()
    channels = await db.get_notification_channels()
    if not channels:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет каналов/групп для уведомлений.", reply_markup=keyboard)
        logger.info(f"Нет каналов для удаления, запрос от @{callback.from_user.username}")
        return
    await callback.message.edit_text("Выберите канал/группу для удаления:",
                                     reply_markup=get_remove_channel_menu(channels))
    logger.debug(f"Запрос удаления канала от @{callback.from_user.username}")


@router.callback_query(F.data.startswith("remove_channel_"))
async def process_remove_channel(callback: CallbackQuery):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка удаления канала от неадминистратора @{callback.from_user.username}")
        return
    channel_id = int(callback.data.split("_")[-1])
    db = Database()
    await db.connect()
    async with db.conn.cursor() as cursor:
        await cursor.execute("SELECT channel_name FROM notification_channels WHERE channel_id = ?", (channel_id,))
        channel_name = (await cursor.fetchone())['channel_name']
        await cursor.execute("DELETE FROM notification_channels WHERE channel_id = ?", (channel_id,))
        await db.conn.commit()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Канал/группа удалена из списка уведомлений.", reply_markup=keyboard)
    logger.info(f"Канал/группа {channel_name} (ID: {channel_id}) удалена пользователем @{callback.from_user.username}")


@router.callback_query(F.data == "edit_channel")
async def edit_channel_prompt(callback: CallbackQuery):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка редактирования канала от неадминистратора @{callback.from_user.username}")
        return
    db = Database()
    await db.connect()
    channels = await db.get_notification_channels()
    if not channels:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Нет каналов/групп для редактирования.", reply_markup=keyboard)
        logger.info(f"Нет каналов для редактирования, запрос от @{callback.from_user.username}")
        return
    await callback.message.edit_text("Выберите канал/группу для редактирования:",
                                     reply_markup=get_edit_channel_menu(channels))
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
    await callback.message.edit_text("Введите новый topic_id (или оставьте пустым для удаления topic_id):",
                                     reply_markup=keyboard)
    await state.set_state(AdminResponse.edit_channel)
    logger.debug(f"Запрос редактирования topic_id для канала ID {channel_id} от @{callback.from_user.username}")


@router.message(StateFilter(AdminResponse.edit_channel))
async def process_edit_channel(message: Message, state: FSMContext):
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка редактирования канала от неадминистратора @{message.from_user.username}")
        return
    try:
        topic_id = int(message.text) if message.text.strip() else None
        data = await state.get_data()
        channel_id = data["channel_id"]
        db = Database()
        await db.connect()
        async with db.conn.cursor() as cursor:
            await cursor.execute("SELECT channel_name FROM notification_channels WHERE channel_id = ?", (channel_id,))
            channel_name = (await cursor.fetchone())['channel_name']
            try:
                await message.bot.send_message(chat_id=channel_id, message_thread_id=topic_id,
                                               text="Тестовое сообщение")
            except TelegramBadRequest:
                await message.answer("Неверный topic_id или канал/группа недоступна.")
                logger.error(f"Неверный topic_id {topic_id} для канала {channel_name} от @{message.from_user.username}")
                return
            await cursor.execute(
                "UPDATE notification_channels SET topic_id = ? WHERE channel_id = ?",
                (topic_id, channel_id)
            )
            await db.conn.commit()
        await message.answer(f"Канал/группа {channel_name} обновлена.")
        logger.info(
            f"Канал/группа {channel_name} (ID: {channel_id}) обновлена с topic_id {topic_id} пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError:
        await message.answer("Введите корректный topic_id или оставьте поле пустым.")
        logger.error(
            f"Неверный формат topic_id {message.text} для канала ID {channel_id} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
        logger.error(
            f"Ошибка редактирования канала: {str(e)} для канала ID {channel_id} от @{message.from_user.username}")


@router.callback_query(F.data == "list_channels")
async def list_channels(callback: CallbackQuery):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка просмотра каналов от неадминистратора @{callback.from_user.username}")
        return
    db = Database()
    await db.connect()
    channels = await db.get_notification_channels()
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
async def process_import(message: Message):
    if message.document.mime_type != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        await message.answer("Отправьте Excel-файл.")
        logger.error(f"Неверный формат файла от @{message.from_user.username}")
        return
    file = await message.bot.get_file(message.document.file_id)
    file_io = await message.bot.download_file(file.file_path)
    result, error = await import_serials(file_io)
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
    await callback.message.edit_text("Отправьте Excel-файл с серийными номерами (столбец 'Serial'):",
                                     reply_markup=keyboard)
    logger.debug(f"Запрос импорта серийников от @{callback.from_user.username}")


@router.callback_query(F.data == "export_serials")
async def export_serials_handler(callback: CallbackQuery):
    output = await export_serials()
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
        document=InputFile(output, filename="serials_export.xlsx"),
        reply_markup=keyboard
    )
    logger.info(f"Экспорт серийников выполнен пользователем @{callback.from_user.username}")


@router.callback_query(F.data == "mark_defect")
async def mark_defect(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите серийный номер и статус (брак/возврат/замена):", reply_markup=keyboard)
    await state.set_state(AdminResponse.mark_defect)
    logger.debug(f"Запрос отметки брака от @{callback.from_user.username}")


@router.message(StateFilter(AdminResponse.mark_defect))
async def process_mark_defect(message: Message, state: FSMContext):
    try:
        serial, status = message.text.split()
        if status not in ["брак", "возврат", "замена"]:
            await message.answer("Статус должен быть: брак, возврат или замена.")
            logger.error(f"Неверный статус {status} для серийника {serial} от @{message.from_user.username}")
            return
        db = Database()
        await db.connect()
        async with db.conn.cursor() as cursor:
            await cursor.execute(
                "UPDATE serials SET return_status = ? WHERE serial = ?",
                (status, serial)
            )
            await db.conn.commit()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer(f"Серийный номер {serial} отмечен как {status}.", reply_markup=keyboard)
        logger.info(f"Серийный номер {serial} отмечен как {status} пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError:
        await message.answer("Неверный формат. Укажите серийный номер и статус через пробел.")
        logger.error(f"Неверный формат ввода для отметки брака от @{message.from_user.username}")


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
async def process_new_time(message: Message, state: FSMContext):
    try:
        hours = float(message.text)
        data = await state.get_data()
        appeal_id = data["appeal_id"]
        db = Database()
        await db.connect()
        async with db.conn.cursor() as cursor:
            await cursor.execute("UPDATE appeals SET status = ? WHERE appeal_id = ?", ("in_progress", appeal_id))
            await db.conn.commit()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer(f"Новое время просрочки установлено: {hours} часов.", reply_markup=keyboard)
        logger.info(
            f"Время просрочки для заявки №{appeal_id} установлено на {hours} часов пользователем @{message.from_user.username}")
        asyncio.create_task(check_overdue(appeal_id, message.bot, hours))
        await state.clear()
    except ValueError:
        await message.answer("Введите число часов.")
        logger.error(f"Неверный формат времени просрочки от @{message.from_user.username}")


@router.callback_query(F.data.startswith("await_specialist_"))
async def await_specialist(callback: CallbackQuery):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка перевода заявки в статус 'Ожидает специалиста' от неадминистратора @{callback.from_user.username}")
        return
    appeal_id = int(callback.data.split("_")[-1])
    db = Database()
    await db.connect()
    appeal = await db.get_appeal(appeal_id)
    async with db.conn.cursor() as cursor:
        await cursor.execute("UPDATE appeals SET status = ? WHERE appeal_id = ?", ("awaiting_specialist", appeal_id))
        await db.conn.commit()
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
        logger.error(
            f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal_id}: {str(e)}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Заявка переведена в статус 'Ожидает выезда специалиста'.", reply_markup=keyboard)
    logger.info(
        f"Заявка №{appeal_id} переведена в статус 'Ожидает специалиста' пользователем @{callback.from_user.username}")


async def check_overdue(appeal_id, bot, hours=24):
    await asyncio.sleep(hours * 3600)
    db = Database()
    await db.connect()
    appeal = await db.get_appeal(appeal_id)
    if appeal["status"] == "in_progress":
        async with db.conn.cursor() as cursor:
            await cursor.execute("UPDATE appeals SET status = ? WHERE appeal_id = ?", ("overdue", appeal_id))
            await db.conn.commit()
        for main_admin_id in MAIN_ADMIN_IDS:
            await bot.send_message(
                main_admin_id,
                f"Заявка №{appeal_id} просрочена.",
                reply_markup=get_overdue_menu(appeal_id)
            )
        logger.info(f"Заявка №{appeal_id} просрочена")


async def check_delegated_overdue(appeal_id, bot, employee_id):
    await asyncio.sleep(12 * 3600)  # 12 часов
    db = Database()
    await db.connect()
    appeal = await db.get_appeal(appeal_id)
    if appeal["status"] in ["in_progress", "postponed"] and appeal["admin_id"] == employee_id:
        for main_admin_id in MAIN_ADMIN_IDS:
            await bot.send_message(
                main_admin_id,
                f"Сотрудник ID {employee_id} не ответил на делегированную заявку №{appeal_id} в течение 12 часов.",
                reply_markup=get_overdue_menu(appeal_id)
            )
        logger.info(f"Делегированная заявка №{appeal_id} не обработана сотрудником ID {employee_id}")