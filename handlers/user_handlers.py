from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    InputMediaPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import (
    get_my_appeals_user_menu,
    get_notification_menu,
    get_channel_take_button,
    get_user_appeal_actions_menu,
)
from utils.validators import validate_media
from utils.statuses import APPEAL_STATUSES
from database.db import (
    add_appeal,
    check_duplicate_appeal,
    get_user_appeals,
    get_appeal,
    get_notification_channels,
    save_response,
)
from datetime import datetime
import json
from config import MAIN_ADMIN_IDS
import logging
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from handlers.common_handlers import UserState, get_start_media

logger = logging.getLogger(__name__)

router = Router()


class AppealForm(StatesGroup):
    serial = State()
    description = State()
    media = State()
    reply_message = State()
    reply_media = State()
    reply_preview = State()


@router.callback_query(F.data == "create_appeal")
async def create_appeal_prompt(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    logger.debug(
        f"Обработка создания заявки для пользователя @{username} (ID: {user_id})"
    )
    data_state = await state.get_data()
    serial = data_state.get("serial")
    if not serial:
        await state.set_state(UserState.waiting_for_auto_delete)
        try:
            await callback.message.edit_text(
                "⚠️В целях безопасности включите автоматическое удаление сообщений через сутки в настройках Telegram.\n"
                "Инструкция в прикреплённых изображениях.⚠️",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Я ВКЛЮЧИЛ АВТОУДАЛЕНИЕ",
                                callback_data="confirm_auto_delete",
                            )
                        ]
                    ]
                ),
            )
            media = get_start_media()
            if media:
                await bot.send_media_group(chat_id=callback.message.chat.id, media=media)
            logger.debug(
                f"Пользователь @{username} (ID: {user_id}) перенаправлен на запрос автоудаления"
            )
        except (TelegramBadRequest, TelegramForbiddenError, FileNotFoundError) as e:
            logger.error(
                f"Ошибка перенаправления на автоудаление для пользователя @{username} (ID: {user_id}): {str(e)}"
            )
            await callback.message.edit_text("Ошибка. Попробуйте снова.")
        await callback.answer()
        return
    await state.set_state(AppealForm.description)
    await callback.message.edit_text(
        "Введите описание проблемы:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        ),
    )
    logger.info(f"Пользователь @{username} (ID: {user_id}) начал создание заявки")
    await callback.answer()


@router.message(StateFilter(AppealForm.description))
async def process_description(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        return
    if not message.text:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await message.answer(
            "Описание не может быть пустым. Введите описание проблемы:",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Пустое описание (нет текста) от @{message.from_user.username} (ID: {message.from_user.id})"
        )
        return
    description = message.text.strip()
    if not description:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await message.answer(
            "Описание не может быть пустым. Введите описание проблемы:",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Пустое описание от @{message.from_user.username} (ID: {message.from_user.id})"
        )
        return
    data = await state.get_data()
    serial = data.get("serial")
    user_id = message.from_user.id
    if await check_duplicate_appeal(serial, description, user_id):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await message.answer(
            "Обращение с таким описанием уже существует. Введите другое описание:",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Дубликат обращения для серийника {serial} от @{message.from_user.username} (ID: {user_id})"
        )
        try:
            await message.delete()
        except TelegramBadRequest as e:
            logger.error(
                f"Ошибка удаления сообщения с описанием от @{message.from_user.username} (ID: {message.from_user.id}): {str(e)}"
            )
        return
    await state.update_data(description=description, media_files=[])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="submit_appeal")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )
    await message.answer(
        "Приложите фото, видео или кружочки (до 10 файлов) или нажмите 'Готово':",
        reply_markup=keyboard,
    )
    try:
        await message.delete()
    except TelegramBadRequest as e:
        logger.error(
            f"Ошибка удаления сообщения с описанием от @{message.from_user.username} (ID: {message.from_user.id}): {str(e)}"
        )
    await state.set_state(AppealForm.media)
    logger.debug(f"Описание принято от @{message.from_user.username} (ID: {user_id})")


@router.message(StateFilter(AppealForm.media))
async def process_media(message: Message, state: FSMContext):
    data = await state.get_data()
    media_files = data.get("media_files", [])
    if len(media_files) >= 10:
        await message.answer(
            "Достигнуто максимальное количество файлов (10). Нажмите 'Готово'.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Готово", callback_data="submit_appeal"
                        )
                    ],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
                ]
            ),
        )
        logger.warning(
            f"Достигнуто максимальное количество файлов для @{message.from_user.username} (ID: {message.from_user.id})"
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="submit_appeal")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )
    is_valid, media = validate_media(message)
    if is_valid:
        file_size = (
            message.photo[-1].file_size
            if message.photo
            else message.video.file_size
            if message.video
            else message.video_note.file_size
        ) / (1024 * 1024)  # в МБ
        if file_size > 200:
            await message.answer(
                "Файл превышает 200 МБ. Приложите файл меньшего размера.",
                reply_markup=keyboard,
            )
            logger.warning(
                f"Файл превышает 200 МБ от @{message.from_user.username} (ID: {message.from_user.id})"
            )
            return
        media_files.extend(media)
        await state.update_data(media_files=media_files)
        try:
            await message.delete()
        except TelegramBadRequest as e:
            logger.error(
                f"Ошибка удаления медиафайла от @{message.from_user.username} (ID: {message.from_user.id}): {str(e)}"
            )
        await message.answer(
            f"Файл добавлен ({len(media_files)}/10). Прикрепите ещё или нажмите 'Готово':",
            reply_markup=keyboard,
        )
        logger.debug(
            f"Медиа ({media[0]['type']}) добавлен пользователем @{message.from_user.username} (ID: {message.from_user.id})"
        )
    else:
        await message.answer(
            "Неподдерживаемый формат. Приложите фото (png/jpeg), видео (mp4) или кружочек (mp4).",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Неподдерживаемый формат медиа от @{message.from_user.username}"
        )


@router.message(StateFilter(AppealForm.reply_message))
async def process_reply_message(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад", callback_data="my_appeals_user"
                        )
                    ]
                ]
            ),
        )
        return
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    reply_text = data_state.get("reply_text", "")
    reply_media = data_state.get("reply_media", [])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Прикрепить медиафайл",
                    callback_data=f"add_reply_media_user_{appeal_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Готово", callback_data=f"preview_reply_user_{appeal_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data=f"view_appeal_user_{appeal_id}"
                )
            ],
        ]
    )
    if message.text:
        reply_text += message.text.strip()
        await state.update_data(reply_text=reply_text)
        try:
            await message.delete()
        except TelegramBadRequest as e:
            logger.error(
                f"Ошибка удаления текстового ответа для заявки №{appeal_id} от @{message.from_user.username} (ID: {message.from_user.id}): {str(e)}"
            )
        await message.answer(
            "Текст добавлен. Прикрепите медиа или нажмите 'Готово':",
            reply_markup=keyboard,
        )
        logger.debug(
            f"Текст ответа добавлен для заявки №{appeal_id} от @{message.from_user.username}"
        )
    else:
        is_valid, media = validate_media(message)
        if is_valid:
            file_size = (
                message.photo[-1].file_size
                if message.photo
                else message.video.file_size
                if message.video
                else message.video_note.file_size
            ) / (1024 * 1024)  # в МБ
            if file_size > 200:
                await message.answer(
                    "Файл превышает 200 МБ. Приложите файл меньшего размера.",
                    reply_markup=keyboard,
                )
                logger.warning(
                    f"Файл превышает 200 МБ от @{message.from_user.username} (ID: {message.from_user.id})"
                )
                return
            reply_media.extend(media)
            await state.update_data(reply_media=reply_media)
            try:
                await message.delete()
            except TelegramBadRequest as e:
                logger.error(
                    f"Ошибка удаления медиафайла ответа для заявки №{appeal_id} от @{message.from_user.username} (ID: {message.from_user.id}): {str(e)}"
                )
            await message.answer(
                f"Медиа добавлено ({len(reply_media)}/10). Прикрепите ещё или нажмите 'Готово':",
                reply_markup=keyboard,
            )
            logger.debug(
                f"Медиа ({media[0]['type']}) добавлено для ответа по заявке №{appeal_id} от @{message.from_user.username}"
            )
        else:
            await message.answer(
                "Неподдерживаемый формат. Приложите фото (png/jpeg), видео (mp4) или кружочек (mp4).",
                reply_markup=keyboard,
            )
            logger.warning(
                f"Неподдерживаемый формат медиа для ответа по заявке №{appeal_id} от @{message.from_user.username}"
            )


@router.callback_query(F.data == "submit_appeal")
async def submit_appeal(callback: CallbackQuery, state: FSMContext, **data):
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
    data_state = await state.get_data()
    serial = data_state.get("serial")
    description = data_state.get("description")
    media_files = data_state.get("media_files", [])
    username = callback.from_user.username or "NoUsername"
    user_id = callback.from_user.id
    duplicate = await check_duplicate_appeal(serial, description, user_id)
    if duplicate:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text(
            "Ошибка: У вас уже есть активная заявка с таким серийным номером и описанием.",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Дублирующая заявка для серийника {serial} от @{callback.from_user.username} (ID: {user_id})"
        )
        await state.clear()
        await state.update_data(serial=serial)
        await callback.answer()
        return
    try:
        appeal_id, appeal_count = await add_appeal(
            serial, username, description, media_files, user_id
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text(
            f"Обращение №{appeal_id} создано!", reply_markup=keyboard
        )
        logger.info(
            f"Обращение №{appeal_id} создано пользователем @{callback.from_user.username} (ID: {user_id})"
        )
        channels = await get_notification_channels()
        logger.debug(f"Найдено каналов для уведомлений: {len(channels)}")
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        appeal_type = "Первая" if appeal_count == 1 else "Повторная"
        text = (
            f"📲 Новая заявка №{appeal_id}:\n\n"
            f"Пользователь: @{username}\n"
            f"Дата создания: {created_at}\n"
            f"Серийный номер: {serial}\n"
            f"Тип заявки: {appeal_type}\n"
            f"Описание: {description}"
        )
        async with db_pool.acquire() as conn:
            for channel in channels:
                try:
                    for media in media_files:
                        if media.get("file_id"):
                            if media["type"] == "photo":
                                await callback.message.bot.send_photo(
                                    chat_id=channel["channel_id"],
                                    message_thread_id=channel["topic_id"],
                                    photo=media["file_id"],
                                )
                            elif media["type"] in ["video", "video_note"]:
                                await callback.message.bot.send_video(
                                    chat_id=channel["channel_id"],
                                    message_thread_id=channel["topic_id"],
                                    video=media["file_id"],
                                )
                    message = await callback.message.bot.send_message(
                        chat_id=channel["channel_id"],
                        message_thread_id=channel["topic_id"],
                        text=text,
                        reply_markup=get_channel_take_button(appeal_id),
                    )
                    # Сохраняем message_id и appeal_id в chat_messages
                    await conn.execute(
                        "INSERT INTO chat_messages (message_id, chat_id, sent_time) VALUES ($1, $2, $3)",
                        message.message_id,
                        channel["channel_id"],
                        f"appeal_id:{appeal_id}",
                    )
                    logger.info(
                        f"Уведомление о заявке №{appeal_id} отправлено в канал {channel['channel_name']} (ID: {channel['channel_id']})"
                    )
                except (TelegramBadRequest, TelegramForbiddenError) as e:
                    logger.error(
                        f"Ошибка отправки в канал {channel['channel_name']} (ID: {channel['channel_id']}) для заявки №{appeal_id}: {str(e)}"
                    )
        recipients = set()
        async with db_pool.acquire() as conn:
            admins = await conn.fetch("SELECT admin_id FROM admins")
            for admin in admins:
                recipients.add(admin["admin_id"])
        recipients.update(MAIN_ADMIN_IDS)
        if not recipients:
            logger.warning("Нет получателей для уведомлений")
        else:
            logger.debug(
                f"Найдено получателей для уведомлений: {len(recipients)}: {list(recipients)}"
            )
            for admin_id in recipients:
                try:
                    for media in media_files:
                        if media.get("file_id"):
                            if media["type"] == "photo":
                                await callback.message.bot.send_photo(
                                    chat_id=admin_id, photo=media["file_id"]
                                )
                            elif media["type"] in ["video", "video_note"]:
                                await callback.message.bot.send_video(
                                    chat_id=admin_id, video=media["file_id"]
                                )
                    await callback.message.bot.send_message(
                        chat_id=admin_id,
                        text=text,
                        reply_markup=get_notification_menu(appeal_id),
                    )
                    logger.info(
                        f"Уведомление о заявке №{appeal_id} отправлено админу ID {admin_id}"
                    )
                except (TelegramBadRequest, TelegramForbiddenError) as e:
                    logger.error(
                        f"Ошибка отправки админу ID {admin_id} для заявки №{appeal_id}: {str(e)}"
                    )
        await state.clear()
        await state.update_data(serial=serial)
        await callback.answer()
    except Exception as e:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text(
            f"Ошибка при создании обращения: {str(e)}", reply_markup=keyboard
        )
        logger.error(f"Ошибка при создании обращения для серийника {serial}: {str(e)}")
        await state.clear()
        await state.update_data(serial=serial)
        await callback.answer()


@router.callback_query(F.data.startswith("submit_reply_user_"))
async def submit_reply_user(callback: CallbackQuery, state: FSMContext, **data):
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
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    reply_text = data_state.get("reply_text", "")
    reply_media = data_state.get("reply_media", [])
    serial = data_state.get("serial")  # Сохраняем serial
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.edit_text(
            "Заявка не найдена.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(
            f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}"
        )
        return
    existing_response = appeal["response"] or ""
    response_lines = existing_response.split("\n") if existing_response else []
    new_response = existing_response
    if reply_text:
        new_response_line = f"[Пользователь] {reply_text}"
        if new_response_line not in response_lines:
            response_lines.append(new_response_line)
    for media in reply_media:
        response_lines.append("[Медиа]")
    new_response = "\n".join(response_lines)
    await save_response(appeal_id, new_response)
    media_files = json.loads(appeal["media_files"] or "[]")
    media_files.extend(reply_media)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE appeals SET media_files = $1 WHERE appeal_id = $2",
            json.dumps(media_files),
            appeal_id,
        )
        await conn.execute(
            "UPDATE appeals SET last_response_time = $1 WHERE appeal_id = $2",
            datetime.now().strftime("%Y-%m-%dT%H:%M"),
            appeal_id,
        )
    try:
        if appeal["admin_id"]:
            for media in reply_media:
                if media.get("file_id"):
                    if media["type"] == "photo":
                        await callback.message.bot.send_photo(
                            chat_id=appeal["admin_id"], photo=media["file_id"]
                        )
                    elif media["type"] in ["video", "video_note"]:
                        await callback.message.bot.send_video(
                            chat_id=appeal["admin_id"], video=media["file_id"]
                        )
            await callback.message.bot.send_message(
                chat_id=appeal["admin_id"],
                text=f"Новый ответ от пользователя по заявке №{appeal_id}:\n{reply_text or 'Медиафайлы'}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Просмотреть заявку",
                                callback_data=f"view_appeal_{appeal_id}",
                            )
                        ]
                    ]
                ),
            )
            logger.info(
                f"Уведомление отправлено администратору ID {appeal['admin_id']} для заявки №{appeal_id}"
            )
        for admin_id in MAIN_ADMIN_IDS:
            if admin_id != appeal["admin_id"]:
                for media in reply_media:
                    if media.get("file_id"):
                        if media["type"] == "photo":
                            await callback.message.bot.send_photo(
                                chat_id=admin_id, photo=media["file_id"]
                            )
                        elif media["type"] in ["video", "video_note"]:
                            await callback.message.bot.send_video(
                                chat_id=admin_id, video=media["file_id"]
                            )
                await callback.message.bot.send_message(
                    chat_id=admin_id,
                    text=f"Новый ответ от пользователя по заявке №{appeal_id}:\n{reply_text or 'Медиафайлы'}",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Просмотреть заявку",
                                    callback_data=f"view_appeal_{appeal_id}",
                                )
                            ]
                        ]
                    ),
                )
                logger.info(
                    f"Уведомление отправлено главному админу ID {admin_id} для заявки №{appeal_id}"
                )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.error(
            f"Ошибка отправки уведомления администратору для заявки №{appeal_id}: {str(e)}"
        )
    try:
        await callback.message.delete()
    except TelegramBadRequest as e:
        logger.error(f"Ошибка удаления сообщения: {str(e)}")
    await callback.message.answer(
        "Ответ отправлен.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data=f"view_appeal_user_{appeal_id}"
                    )
                ]
            ]
        ),
    )
    await state.clear()
    await state.update_data(serial=serial)  # Сохраняем serial
    logger.info(
        f"Ответ по заявке №{appeal_id} отправлен пользователем @{callback.from_user.username}"
    )
    await callback.answer()


@router.callback_query(F.data == "my_appeals_user")
async def show_my_appeals_user(callback: CallbackQuery, **data):
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
    user_id = callback.from_user.id
    appeals = await get_user_appeals(user_id)
    if not appeals:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("У вас нет заявок.", reply_markup=keyboard)
        logger.info(
            f"У пользователя @{callback.from_user.username} (ID: {user_id}) нет заявок"
        )
        return
    await callback.message.delete()
    await callback.message.answer(
        "Ваши обращения:", reply_markup=get_my_appeals_user_menu(appeals)
    )
    logger.info(
        f"Пользователь @{callback.from_user.username} (ID: {user_id}) запросил свои заявки, найдено: {len(appeals)}"
    )


@router.callback_query(F.data.startswith("view_appeal_user_"))
async def view_appeal_user(callback: CallbackQuery, state: FSMContext, **data):
    appeal_id = int(callback.data.split("_")[-1])
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.delete()
        await callback.message.answer(
            "Заявка не найдена.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(
            f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}"
        )
        return
    media_files = json.loads(appeal["media_files"] or "[]")  # Проверяем наличие медиа
    response = (
        f"Заявка №{appeal['appeal_id']}:\n"
        f"Серийный номер: {appeal['serial']}\n"
        f"Дата создания: {appeal['created_time']}\n"
        f"Статус: {APPEAL_STATUSES.get(appeal['status'], appeal['status'])}\n"
        f"Описание: {appeal['description']}\n"
        f"Ответ: {appeal['response'] or 'Нет ответа'}"
    )
    keyboard = get_user_appeal_actions_menu(
        appeal_id=appeal_id,
        status=appeal["status"],
        media_count=len(media_files),
    )
    await callback.message.delete()
    await callback.message.answer(response, reply_markup=keyboard)
    logger.info(
        f"Заявка №{appeal_id} просмотрена пользователем @{callback.from_user.username}"
    )


@router.callback_query(F.data.startswith("show_media_user_"))
async def show_user_media(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.delete()
        await callback.message.answer(
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
    if not appeal:
        await callback.message.delete()
        await callback.message.answer(
            "Заявка не найдена.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(
            f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}"
        )
        return
    media_files = json.loads(appeal["media_files"] or "[]")
    if not media_files:
        await callback.message.delete()
        await callback.message.answer(
            "Медиафайлы отсутствуют.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data=f"view_appeal_user_{appeal_id}",
                        )
                    ]
                ]
            ),
        )
        logger.info(f"Медиафайлы отсутствуют для заявки №{appeal_id}")
        return
    await callback.message.delete()
    for media in media_files:
        try:
            if media.get("file_id"):
                if media["type"] == "photo":
                    await callback.message.bot.send_photo(
                        chat_id=callback.from_user.id, photo=media["file_id"]
                    )
                elif media["type"] in ["video", "video_note"]:
                    await callback.message.bot.send_video(
                        chat_id=callback.from_user.id, video=media["file_id"]
                    )
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            logger.error(
                f"Ошибка отправки медиа (тип: {media['type']}, file_id: {media.get('file_id')}) для заявки №{appeal_id}: {str(e)}"
            )
    await callback.message.answer(
        "Медиафайлы отображены.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data=f"view_appeal_user_{appeal_id}"
                    )
                ]
            ]
        ),
    )
    logger.info(
        f"Медиафайлы для заявки №{appeal_id} отображены для @{callback.from_user.username}"
    )


@router.callback_query(F.data.in_(["prepare_launch", "setup_remote", "setup_nsu"]))
async def process_placeholder(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "Эта функция находится в разработке.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        ),
    )
    logger.debug(
        f"Пользователь @{callback.from_user.username} запросил заглушку: {callback.data}"
    )


@router.callback_query(F.data.startswith("reply_user_"))
async def reply_user_prompt(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    logger.debug(
        f"Запрос ответа для заявки №{appeal_id} от пользователя @{username} (ID: {user_id})"
    )
    appeal = await get_appeal(appeal_id)
    if not appeal:
        await callback.message.delete()
        await callback.message.answer(
            "Заявка не найдена.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(f"Заявка №{appeal_id} не найдена пользователем @{username}")
        return
    await state.update_data(
        appeal_id=appeal_id, reply_text="", reply_media=[]
    )  # Сохраняем appeal_id
    await state.set_state(AppealForm.reply_message)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data=f"view_appeal_user_{appeal_id}"
                )
            ]
        ]
    )
    await callback.message.delete()
    await callback.message.answer(
        "Введите ответ по заявке или прикрепите медиа:", reply_markup=keyboard
    )
    logger.debug(
        f"Состояние FSM установлено для ответа по заявке №{appeal_id} от @{username}"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("preview_reply_user_"))
async def preview_reply_user(callback: CallbackQuery, state: FSMContext):
    data_state = await state.get_data()
    appeal_id = data_state["appeal_id"]
    reply_text = data_state.get("reply_text", "")
    reply_media = data_state.get("reply_media", [])
    text = f"Предпросмотр ответа:\nТекст: {reply_text or 'Отсутствует'}\nМедиафайлы: {len(reply_media)}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отправить", callback_data=f"submit_reply_user_{appeal_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Редактировать", callback_data=f"edit_reply_user_{appeal_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"cancel_reply_user_{appeal_id}"
                )
            ],
        ]
    )
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=keyboard)
    logger.debug(
        f"Предпросмотр ответа для заявки №{appeal_id} от @{callback.from_user.username}"
    )


@router.callback_query(F.data.startswith("edit_reply_user_"))
async def edit_reply_user(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменить текст",
                    callback_data=f"change_reply_text_user_{appeal_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Добавить медиа",
                    callback_data=f"add_reply_media_user_{appeal_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отправить", callback_data=f"submit_reply_user_{appeal_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"cancel_reply_user_{appeal_id}"
                )
            ],
        ]
    )
    await callback.message.delete()
    await callback.message.answer("Редактирование ответа:", reply_markup=keyboard)
    logger.debug(
        f"Редактирование ответа для заявки №{appeal_id} от @{callback.from_user.username}"
    )


@router.callback_query(F.data.startswith("change_reply_text_user_"))
async def change_reply_text_user(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data=f"edit_reply_user_{appeal_id}"
                )
            ]
        ]
    )
    await callback.message.delete()
    await callback.message.answer("Введите новый текст ответа:", reply_markup=keyboard)
    await state.set_state(AppealForm.reply_message)
    logger.debug(
        f"Изменение текста ответа для заявки №{appeal_id} от @{callback.from_user.username}"
    )


@router.callback_query(F.data.startswith("add_reply_media_user_"))
async def add_reply_media_user(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    data_state = await state.get_data()
    reply_media = data_state.get("reply_media", [])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Готово", callback_data=f"preview_reply_user_{appeal_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data=f"edit_reply_user_{appeal_id}"
                )
            ],
        ]
    )
    await callback.message.delete()
    await callback.message.answer(
        f"Приложите фото, видео или кружочки (до 10 файлов, текущих: {len(reply_media)}):",
        reply_markup=keyboard,
    )
    await state.set_state(AppealForm.reply_message)
    logger.debug(
        f"Добавление медиа для ответа по заявке №{appeal_id} от @{callback.from_user.username}"
    )


@router.callback_query(F.data.startswith("cancel_reply_user_"))
async def cancel_reply_user(callback: CallbackQuery, state: FSMContext):
    appeal_id = int(callback.data.split("_")[-1])
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        "Ответ отменён.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data=f"view_appeal_user_{appeal_id}"
                    )
                ]
            ]
        ),
    )
    logger.info(
        f"Ответ для заявки №{appeal_id} отменён пользователем @{callback.from_user.username}"
    )


@router.callback_query(F.data.startswith("close_appeal_user_"))
async def close_appeal_user(callback: CallbackQuery, **data):
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
    if not appeal:
        await callback.message.delete()
        await callback.message.answer(
            "Заявка не найдена.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(
            f"Заявка №{appeal_id} не найдена пользователем @{callback.from_user.username}"
        )
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE appeals SET status = 'closed', closed_time = $1 WHERE appeal_id = $2",
            datetime.now().strftime("%Y-%m-%dT%H:%M"),
            appeal_id,
        )
    await callback.message.delete()
    await callback.message.answer(
        f"Заявка №{appeal_id} закрыта.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        ),
    )
    logger.info(
        f"Заявка №{appeal_id} закрыта пользователем @{callback.from_user.username}"
    )
    await callback.answer()
