from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from keyboards.inline import get_user_menu, get_my_appeals_user_menu, get_admin_menu, get_notification_menu, get_channel_take_button
from utils.validators import validate_serial, validate_media
from utils.statuses import APPEAL_STATUSES
from database.db import add_appeal, check_duplicate_appeal, get_user_appeals, get_appeal, get_notification_channels
from datetime import datetime
import json
from config import MAIN_ADMIN_IDS
import logging
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

router = Router()

class AppealForm(StatesGroup):
    serial = State()
    description = State()
    media = State()
    reply_message = State()

class UserState(StatesGroup):
    waiting_for_serial = State()
    menu = State()

@router.message(Command(commands=["start"]))
async def start_command(message: Message, state: FSMContext, **data):
    db_pool = data["db_pool"]
    user_id = message.from_user.id
    is_admin = False
    async with db_pool.acquire() as conn:
        admin = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True
    if is_admin:
        await message.answer("Добро пожаловать, администратор!", reply_markup=get_admin_menu(user_id))
        logger.debug(f"Админ @{message.from_user.username} (ID: {user_id}) получил админское меню")
        await state.clear()
    else:
        await message.answer("Введите серийный номер устройства:")
        await state.set_state(UserState.waiting_for_serial)
        logger.debug(f"Пользователь @{message.from_user.username} (ID: {user_id}) начал ввод серийного номера")

@router.message(UserState.waiting_for_serial)
async def process_initial_serial(message: Message, state: FSMContext, **data):
    serial = message.text
    if not validate_serial(serial):
        await message.answer("Неверный формат серийного номера (A-Za-z0-9, 8–20 символов). Попробуйте снова:")
        logger.warning(f"Неверный серийный номер {serial} от @{message.from_user.username} (ID: {message.from_user.id})")
        return
    db_pool = data["db_pool"]
    async with db_pool.acquire() as conn:
        serial_exists = await conn.fetchrow("SELECT * FROM serials WHERE serial = $1", serial)
    if not serial_exists:
        await message.answer("Серийный номер не найден в базе. Попробуйте снова:")
        logger.warning(f"Серийный номер {serial} не найден, попытка от @{message.from_user.username} (ID: {message.from_user.id})")
        return
    await state.update_data(serial=serial)
    await state.set_state(UserState.menu)
    await message.answer("Добро пожаловать!", reply_markup=get_user_menu())
    logger.debug(f"Серийный номер {serial} принят, пользователь @{message.from_user.username} (ID: {message.from_user.id}) получил меню")

@router.callback_query(F.data == "create_appeal")
async def create_appeal(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите серийный номер:", reply_markup=keyboard)
    await state.set_state(AppealForm.serial)
    logger.debug(f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) начал создание обращения")

@router.message(AppealForm.serial)
async def process_serial(message: Message, state: FSMContext, **data):
    serial = message.text
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    if not validate_serial(serial):
        await message.answer("Неверный формат серийного номера (A-Za-z0-9, 8–20 символов). Попробуйте снова:", reply_markup=keyboard)
        logger.warning(f"Неверный серийный номер {serial} от @{message.from_user.username} (ID: {message.from_user.id})")
        return
    db_pool = data["db_pool"]
    async with db_pool.acquire() as conn:
        serial_exists = await conn.fetchrow("SELECT * FROM serials WHERE serial = $1", serial)
    if not serial_exists:
        await message.answer("Серийный номер не найден в базе.", reply_markup=keyboard)
        logger.warning(f"Серийный номер {serial} не найден, попытка от @{message.from_user.username} (ID: {message.from_user.id})")
        await state.clear()
        return
    await state.update_data(serial=serial, user_id=message.from_user.id)
    await message.answer("Опишите проблему:", reply_markup=keyboard)
    await state.set_state(AppealForm.description)
    logger.debug(f"Серийный номер {serial} принят от @{message.from_user.username} (ID: {message.from_user.id})")

@router.message(AppealForm.description)
async def process_description(message: Message, state: FSMContext):
    description = message.text.strip() if message.text else ""
    if not description:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await message.answer("Описание не может быть пустым. Пожалуйста, введите описание проблемы:", reply_markup=keyboard)
        logger.warning(f"Пустое описание от @{message.from_user.username} (ID: {message.from_user.id})")
        return
    await state.update_data(description=description)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data="done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await message.answer("Приложите фото/видео/кружочки (до 200 МБ, или нажмите 'Готово' для завершения):", reply_markup=keyboard)
    await state.set_state(AppealForm.media)
    logger.debug(f"Описание принято от @{message.from_user.username} (ID: {message.from_user.id}): {description}")

@router.message(AppealForm.media)
async def process_media(message: Message, state: FSMContext, **data):
    data_state = await state.get_data()
    media_files = data_state.get("media_files", [])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data="done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    is_valid, media_type = validate_media(message)
    if is_valid:
        file_size = (message.photo[-1].file_size if message.photo else
                     message.video.file_size if message.video else
                     message.video_note.file_size) / (1024 * 1024)  # в МБ
        if file_size > 200:
            await message.answer("Файл превышает 200 МБ. Приложите файл меньшего размера.", reply_markup=keyboard)
            logger.warning(f"Файл превышает 200 МБ от @{message.from_user.username} (ID: {message.from_user.id})")
            return
        file_id = (message.photo[-1].file_id if message.photo else
                   message.video.file_id if message.video else
                   message.video_note.file_id)
        media_files.append({
            "type": media_type,
            "file_id": file_id
        })
        await state.update_data(media_files=media_files)
        await message.answer("Файл добавлен. Приложите ещё или нажмите 'Готово':", reply_markup=keyboard)
        logger.debug(f"Медиафайл ({media_type}) добавлен пользователем @{message.from_user.username} (ID: {message.from_user.id})")
    else:
        await message.answer("Неподдерживаемый формат медиа. Приложите фото, видео или кружочек.", reply_markup=keyboard)
        logger.warning(f"Неподдерживаемый формат медиа от @{message.from_user.username} (ID: {message.from_user.id})")

@router.callback_query(F.data == "done")
async def process_done(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data["db_pool"]
    data_state = await state.get_data()
    media_files = data_state.get("media_files", [])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    duplicate = await check_duplicate_appeal(data_state["serial"], data_state["description"], data_state["user_id"])
    if duplicate:
        await callback.message.edit_text("Ошибка: У вас уже есть активная заявка с таким серийным номером и описанием.",
                                        reply_markup=keyboard)
        logger.warning(f"Дублирующая заявка для серийника {data_state['serial']} от @{callback.from_user.username} (ID: {data_state['user_id']})")
        await state.clear()
        await callback.answer()
        return
    try:
        appeal_id, appeal_count = await add_appeal(data_state["serial"], callback.from_user.username, data_state["description"],
                                                  media_files, data_state["user_id"])
        await callback.message.edit_text("Обращение создано!", reply_markup=keyboard)
        logger.info(f"Обращение №{appeal_id} создано пользователем @{callback.from_user.username} (ID: {data_state['user_id']})")
        channels = await get_notification_channels()
        logger.debug(f"Найдено каналов для уведомлений: {len(channels)}")
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        appeal_type = "Первая" if appeal_count == 1 else "Повторная"
        text = (f"📲 Новая заявка №{appeal_id}:\n\n"
                f"Пользователь: @{callback.from_user.username}\n"
                f"Дата создания: {created_at}\n"
                f"Серийный номер: {data_state['serial']}\n"
                f"Тип заявки: {appeal_type}\n"
                f"Описание: {data_state['description']}")
        # Разделяем медиа по типам
        photo_group = []
        video_group = []
        for media in media_files:
            if media["type"] == "photo" and media.get("file_id"):
                photo_group.append(InputMediaPhoto(media=media["file_id"]))
            elif media["type"] in ["video", "video_note"] and media.get("file_id"):
                video_group.append(InputMediaVideo(media=media["file_id"]))
        # Отправка уведомлений в каналы
        for channel in channels:
            try:
                if photo_group:
                    await callback.message.bot.send_media_group(
                        chat_id=channel["channel_id"],
                        message_thread_id=channel["topic_id"],
                        media=photo_group
                    )
                if video_group:
                    await callback.message.bot.send_media_group(
                        chat_id=channel["channel_id"],
                        message_thread_id=channel["topic_id"],
                        media=video_group
                    )
                await callback.message.bot.send_message(
                    chat_id=channel["channel_id"],
                    message_thread_id=channel["topic_id"],
                    text=text,
                    reply_markup=get_channel_take_button(appeal_id)
                )
                logger.info(f"Уведомление о заявке №{appeal_id} отправлено в канал {channel['channel_name']} (ID: {channel['channel_id']})")
            except TelegramBadRequest as e:
                logger.error(f"Ошибка отправки уведомления в канал {channel['channel_name']} (ID: {channel['channel_id']}) для заявки №{appeal_id}: {str(e)}")
        # Отправка уведомлений администраторам
        recipients = set()
        async with db_pool.acquire() as conn:
            admins = await conn.fetch("SELECT admin_id FROM admins")
            for admin in admins:
                recipients.add(admin["admin_id"])
        recipients.update(MAIN_ADMIN_IDS)
        if not recipients:
            logger.warning("Нет получателей для уведомлений")
        else:
            logger.debug(f"Найдено получателей для уведомлений: {len(recipients)}: {list(recipients)}")
            for admin_id in recipients:
                try:
                    if photo_group:
                        await callback.message.bot.send_media_group(
                            chat_id=admin_id,
                            media=photo_group
                        )
                    if video_group:
                        await callback.message.bot.send_media_group(
                            chat_id=admin_id,
                            media=video_group
                        )
                    await callback.message.bot.send_message(
                        chat_id=admin_id,
                        text=text,
                        reply_markup=get_notification_menu(appeal_id)
                    )
                    logger.info(f"Уведомление о заявке №{appeal_id} отправлено админу ID {admin_id}")
                except TelegramBadRequest as e:
                    logger.error(f"Ошибка отправки уведомления админу ID {admin_id} для заявки №{appeal_id}: {str(e)}")
                    continue
        await state.clear()
        await callback.answer()
    except ValueError as e:
        await callback.message.edit_text(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(f"Ошибка при создании обращения для серийника {data_state['serial']}: {str(e)}")
        await state.clear()
        await callback.answer()
    except Exception as e:
        await callback.message.edit_text("Произошла ошибка при создании обращения. Попробуйте позже.", reply_markup=keyboard)
        logger.error(f"Неизвестная ошибка при создании обращения для серийника {data_state['serial']}: {str(e)}")
        await state.clear()
        await callback.answer()

@router.callback_query(F.data.in_(["prepare_launch", "setup_remote", "setup_nsu"]))
async def process_placeholder(callback: CallbackQuery):
    await callback.message.edit_text("Эта функция находится в разработке.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ]))
    logger.debug(f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) запросил заглушку: {callback.data}")
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def return_to_main_menu(callback: CallbackQuery, state: FSMContext, **data):
    user_id = callback.from_user.id
    username = callback.from_user.username
    db_pool = data["db_pool"]
    is_admin = False
    async with db_pool.acquire() as conn:
        admin = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True

    if state:
        await state.clear()

    if callback.message.content_type == 'text':
        if is_admin:
            await callback.message.edit_text(
                "Добро пожаловать, администратор!",
                reply_markup=get_admin_menu(user_id)
            )
        else:
            await callback.message.edit_text(
                "Добро пожаловать!",
                reply_markup=get_user_menu()
            )
    else:
        await callback.message.delete()
        if is_admin:
            await callback.message.bot.send_message(
                chat_id=callback.from_user.id,
                text="Добро пожаловать, администратор!",
                reply_markup=get_admin_menu(user_id)
            )
        else:
            await callback.message.bot.send_message(
                chat_id=callback.from_user.id,
                text="Добро пожаловать!",
                reply_markup=get_user_menu()
            )
    logger.debug(f"Пользователь @{username} (ID: {user_id}) вернулся в главное меню")

@router.callback_query(F.data == "my_appeals_user")
async def show_my_appeals_user(callback: CallbackQuery, **data):
    appeals = await get_user_appeals(callback.from_user.id)
    if not appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("У вас нет заявок.", reply_markup=keyboard)
        logger.info(f"У пользователя @{callback.from_user.username} (ID: {callback.from_user.id}) нет заявок")
        return
    await callback.message.edit_text("Ваши заявки:", reply_markup=get_my_appeals_user_menu(appeals))
    logger.info(f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) запросил свои обращения")

@router.callback_query(F.data.startswith("view_appeal_user_"))
async def view_appeal_user(callback: CallbackQuery, **data):
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals_user")]
        ])
        await callback.message.edit_text("Заявка не найдена.", reply_markup=keyboard)
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username} (ID: {callback.from_user.id})")
        return
    created_time = datetime.strptime(appeal['created_time'], "%Y-%m-%dT%H:%M").strftime("%Y-%m-%d %H:%M")
    new_serial_text = f"\nНовый серийник: {appeal['new_serial']}" if appeal['new_serial'] else ""
    response_text = f"\nДиалог:\n{appeal['response']}" if appeal['response'] else ""
    text = (f"Заявка №{appeal['appeal_id']}:\n"
            f"Заявитель: @{appeal['username']}\n"
            f"Серийный номер: {appeal['serial']}\n"
            f"Описание: {appeal['description']}\n"
            f"Статус: {APPEAL_STATUSES.get(appeal['status'], appeal['status'])}\n"
            f"Дата создания: {created_time}{new_serial_text}{response_text}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals_user")]
    ])
    if appeal['status'] == "in_progress":
        keyboard.inline_keyboard.insert(0, [
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_appeal_{appeal_id}")
        ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    logger.info(f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) просмотрел заявку №{appeal_id}")

@router.callback_query(F.data.startswith("reply_appeal_"))
async def reply_appeal(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data=f"done_reply_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals_user")]
    ])
    await callback.message.edit_text(
        "Введите ваш ответ по заявке (или нажмите 'Готово' для завершения):",
        reply_markup=keyboard
    )
    await state.set_state(AppealForm.reply_message)
    await state.update_data(appeal_id=appeal_id)
    logger.debug(f"Запрос ответа для заявки №{appeal_id} от пользователя @{callback.from_user.username}")

@router.message(StateFilter(AppealForm.reply_message))
async def process_reply_message(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals_user")]
        ]))
        return
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    appeal = await get_appeal(appeal_id)
    response = message.text.strip() if message.text else None
    if response:
        async with db_pool.acquire() as conn:
            existing_response = appeal['response'] or ""
            new_response = f"{existing_response}\n[Пользователь] {response}" if existing_response else f"[Пользователь] {response}"
            await conn.execute(
                "UPDATE appeals SET response = $1 WHERE appeal_id = $2",
                new_response, appeal_id
            )
        try:
            await message.bot.send_message(
                chat_id=appeal["admin_id"],
                text=f"Новый ответ от пользователя по заявке №{appeal_id}:\n{response}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Просмотреть заявку", callback_data=f"view_appeal_{appeal_id}")]
                ])
            )
            logger.debug(f"Уведомление отправлено администратору ID {appeal['admin_id']} для заявки №{appeal_id}")
        except TelegramBadRequest as e:
            logger.error(f"Ошибка отправки уведомления администратору ID {appeal['admin_id']} для заявки №{appeal_id}: {str(e)}")
        channels = await get_notification_channels()
        for channel in channels:
            try:
                await message.bot.send_message(
                    chat_id=channel["channel_id"],
                    message_thread_id=channel["topic_id"],
                    text=f"Новый ответ от пользователя по заявке №{appeal_id}:\n{response}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Просмотреть заявку", callback_data=f"view_appeal_{appeal_id}")]
                    ])
                )
            except TelegramBadRequest as e:
                logger.error(f"Ошибка отправки в канал {channel['channel_name']}: {str(e)}")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals_user")]
    ])
    await message.answer("Ответ отправлен. Вернитесь к вашим обращениям:", reply_markup=keyboard)
    await state.clear()
    logger.info(f"Ответ по заявке №{appeal_id} отправлен пользователем @{message.from_user.username}")

@router.callback_query(F.data.startswith("done_reply_"))
async def done_reply(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals_user")]
    ])
    await callback.message.edit_text("Ответ не введён. Вернитесь к вашим обращениям:", reply_markup=keyboard)
    await state.clear()
    logger.info(f"Завершение ответа без текста для заявки №{appeal_id} пользователем @{callback.from_user.username}")
    await callback.answer()