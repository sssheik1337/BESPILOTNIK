from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from keyboards.inline import get_user_menu, get_my_appeals_user_menu, get_admin_menu, get_notification_menu, get_channel_take_button
from utils.validators import validate_serial, validate_media
from database.models import Database
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

@router.callback_query(F.data == "create_appeal")
async def create_appeal(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите серийный номер:", reply_markup=keyboard)
    await state.set_state(AppealForm.serial)
    logger.debug(f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) начал создание обращения")

@router.message(AppealForm.serial)
async def process_serial(message: Message, state: FSMContext):
    serial = message.text
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    if not validate_serial(serial):
        await message.answer("Неверный формат серийного номера (A-Za-z0-9, 8–20 символов). Попробуйте снова:", reply_markup=keyboard)
        logger.warning(f"Неверный серийный номер {serial} от @{message.from_user.username} (ID: {message.from_user.id})")
        return
    db = Database()
    await db.connect()
    async with db.conn.cursor() as cursor:
        await cursor.execute("SELECT * FROM serials WHERE serial = ?", (serial,))
        serial_exists = await cursor.fetchone()
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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await message.answer("Приложите фото/видео/кружочки (до 200 МБ, или отправьте 'Готово' для завершения):", reply_markup=keyboard)
    await state.set_state(AppealForm.media)
    logger.debug(f"Описание принято от @{message.from_user.username} (ID: {message.from_user.id}): {description}")

@router.message(AppealForm.media)
async def process_media(message: Message, state: FSMContext):
    data = await state.get_data()
    media_files = data.get("media_files", [])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    is_valid, media_type = validate_media(message)
    if message.text and message.text.lower() == "готово":
        db = Database()
        await db.connect()
        duplicate = await db.check_duplicate_appeal(data["serial"], data["description"], data["user_id"])
        if duplicate:
            await message.answer("Ошибка: У вас уже есть активная заявка с таким серийным номером и описанием.",
                                 reply_markup=keyboard)
            logger.warning(f"Дублирующая заявка для серийника {data['serial']} от @{message.from_user.username} (ID: {data['user_id']})")
            await state.clear()
            return
        appeal_id, appeal_count = await db.add_appeal(data["serial"], message.from_user.username, data["description"],
                                                      media_files, data["user_id"])
        await message.answer("Обращение создано!", reply_markup=keyboard)
        logger.info(f"Обращение №{appeal_id} создано пользователем @{message.from_user.username} (ID: {data['user_id']})")
        channels = await db.get_notification_channels()
        logger.debug(f"Найдено каналов для уведомлений: {len(channels)}")
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        appeal_type = "Первая" if appeal_count == 1 else "Повторная"
        text = (f"📲 Новая заявка №{appeal_id}:\n\n"
                f"Пользователь: @{message.from_user.username}\n"
                f"Дата создания: {created_at}\n"
                f"Серийный номер: {data['serial']}\n"
                f"Тип заявки: {appeal_type}\n"
                f"Описание: {data['description']}")
        for channel in channels:
            logger.debug(f"Отправка уведомления в канал {channel['channel_name']} (ID: {channel['channel_id']})")
            media_group = []
            for media in media_files:
                if media["type"] == "photo":
                    media_group.append(InputMediaPhoto(media=media["file_id"]))
                elif media["type"] in ["video", "video_note"]:
                    media_group.append(InputMediaVideo(media=media["file_id"]))
            try:
                if media_group:
                    await message.bot.send_media_group(
                        chat_id=channel["channel_id"],
                        message_thread_id=channel["topic_id"],
                        media=media_group
                    )
                logger.debug(f"Вызов get_channel_take_button для заявки №{appeal_id}")
                await message.bot.send_message(
                    chat_id=channel["channel_id"],
                    message_thread_id=channel["topic_id"],
                    text=text,
                    reply_markup=get_channel_take_button(appeal_id)
                )
                logger.info(f"Уведомление о заявке №{appeal_id} отправлено в канал {channel['channel_name']} (ID: {channel['channel_id']})")
            except TelegramBadRequest as e:
                logger.error(f"Ошибка отправки уведомления в канал {channel['channel_name']} (ID: {channel['channel_id']}) для заявки №{appeal_id}: {str(e)}")
        recipients = set()
        async with db.conn.cursor() as cursor:
            await cursor.execute("SELECT admin_id FROM admins")
            admins = await cursor.fetchall()
            for admin in admins:
                recipients.add(admin["admin_id"])
        recipients.update(MAIN_ADMIN_IDS)
        if not recipients:
            logger.warning("Нет получателей для уведомлений")
        else:
            logger.debug(f"Найдено получателей для уведомлений: {len(recipients)}: {list(recipients)}")
            for admin_id in recipients:
                media_group = []
                for media in media_files:
                    if media["type"] == "photo" and media.get("file_id"):
                        media_group.append(InputMediaPhoto(media=media["file_id"]))
                    elif media["type"] in ["video", "video_note"] and media.get("file_id"):
                        media_group.append(InputMediaVideo(media=media["file_id"]))
                try:
                    if media_group:
                        await message.bot.send_media_group(
                            chat_id=admin_id,
                            media=media_group
                        )
                    await message.bot.send_message(
                        chat_id=admin_id,
                        text=text,
                        reply_markup=get_notification_menu(appeal_id)
                    )
                    logger.info(f"Уведомление о заявке №{appeal_id} отправлено админу ID {admin_id}")
                except TelegramBadRequest as e:
                    logger.error(f"Ошибка отправки уведомления админу ID {admin_id} для заявки №{appeal_id}: {str(e)}")
                    continue
        await state.clear()
    elif is_valid:
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
        await message.answer("Файл добавлен. Приложите ещё или отправьте 'Готово':", reply_markup=keyboard)
        logger.debug(f"Медиафайл добавлен пользователем @{message.from_user.username} (ID: {message.from_user.id})")
    else:
        await message.answer("Неподдерживаемый формат медиа. Приложите фото, видео или кружочек.", reply_markup=keyboard)
        logger.warning(f"Неподдерживаемый формат медиа от @{message.from_user.username} (ID: {message.from_user.id})")


@router.callback_query(F.data == "main_menu")
async def return_to_main_menu(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username

    # Проверка, является ли пользователь администратором
    db = Database()
    await db.connect()
    is_admin = False
    async with db.conn.cursor() as cursor:
        await cursor.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,))
        admin = await cursor.fetchone()
        if admin or user_id in MAIN_ADMIN_IDS:
            is_admin = True

    if state:
        await state.clear()

    # Проверяем тип сообщения
    if callback.message.content_type == 'text':
        # Если сообщение текстовое, редактируем его
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
        # Если сообщение содержит файл, удаляем его и отправляем новое
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

@router.callback_query(F.data == "my_appeals_user")
async def show_my_appeals_user(callback: CallbackQuery):
    db = Database()
    await db.connect()
    appeals = await db.get_user_appeals(callback.from_user.id)
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
async def view_appeal_user(callback: CallbackQuery):
    appeal_id = int(callback.data.split("_")[-1])
    db = Database()
    await db.connect()
    appeal = await db.get_appeal(appeal_id)
    if not appeal:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Заявка не найдена.", reply_markup=keyboard)
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username} (ID: {callback.from_user.id})")
        return
    created_time = datetime.strptime(appeal['created_time'], "%Y-%m-%dT%H:%M:%S.%f").strftime("%Y-%m-%d %H:%M:%S")
    text = (f"Заявка №{appeal['appeal_id']}:\n"
            f"Серийный номер: {appeal['serial']}\n"
            f"Описание: {appeal['description']}\n"
            f"Статус: {appeal['status']}\n"
            f"Дата создания: {created_time}")
    if appeal['response'] is not None:
        text += f"\nОтвет: {appeal['response']}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals_user")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    logger.info(f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) просмотрел заявку №{appeal_id}")