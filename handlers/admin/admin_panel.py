from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_admin_panel_menu, get_remove_channel_menu, get_edit_channel_menu
from database.db import add_admin, add_notification_channel, get_notification_channels
from config import MAIN_ADMIN_IDS
import logging
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

router = Router()

class AdminResponse(StatesGroup):
    add_channel = State()
    edit_channel = State()
    add_employee = State()

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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
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
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ]))
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ])
        await message.answer("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка добавления сотрудника от неадминистратора @{message.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError("Формат: ID @username или ID Нет")
        admin_id = int(parts[0])
        username = parts[1].lstrip("@") if parts[1] != "Нет" else None
        await add_admin(admin_id, username)
        await message.answer(f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен.", reply_markup=keyboard)
        logger.info(f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(f"Неверный формат ввода сотрудника {message.text} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
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
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ]))
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ])
        await message.answer("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка добавления канала от неадминистратора @{message.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])
    try:
        parts = message.text.split()
        if len(parts) not in [1, 2]:
            raise ValueError("Формат: @username [topic_id]")
        channel_name = parts[0]
        topic_id = int(parts[1]) if len(parts) == 2 else None
        if not channel_name.startswith("@"):
            raise ValueError("Название канала должно начинаться с @")
        chat = await message.bot.get_chat(channel_name)
        channel_id = chat.id
        admins = await message.bot.get_chat_administrators(channel_id)
        bot_id = (await message.bot.get_me()).id
        if not any(admin.user.id == bot_id for admin in admins):
            await message.answer("Бот должен быть администратором в группе/канале.", reply_markup=keyboard)
            logger.error(f"Бот не является администратором в канале {channel_name} при добавлении от @{message.from_user.username}")
            return
        try:
            await message.bot.send_message(chat_id=channel_id, message_thread_id=topic_id, text="Тестовое сообщение")
        except TelegramBadRequest:
            await message.answer("Канал/группа недоступна или topic_id неверный.", reply_markup=keyboard)
            logger.error(f"Неверный topic_id {topic_id} для канала {channel_name} от @{message.from_user.username}")
            return
        await add_notification_channel(channel_id, channel_name, topic_id)
        await message.answer(f"Канал/группа {channel_name} добавлена для уведомлений.", reply_markup=keyboard)
        logger.info(f"Канал/группа {channel_name} (ID: {channel_id}, topic_id: {topic_id}) добавлена пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(f"Неверный формат ввода канала {message.text} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_channel")]
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
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_channel")]
        ]))
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_channel")]
        ])
        await message.answer("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка редактирования канала от неадминистратора @{message.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_channel")]
    ])
    try:
        topic_id = int(message.text) if message.text.strip() else None
        data_state = await state.get_data()
        channel_id = data_state["channel_id"]
        async with db_pool.acquire() as conn:
            channel_name = await conn.fetchval("SELECT channel_name FROM notification_channels WHERE channel_id = $1", channel_id)
            try:
                await message.bot.send_message(chat_id=channel_id, message_thread_id=topic_id, text="Тестовое сообщение")
            except TelegramBadRequest:
                await message.answer("Неверный topic_id или канал/группа недоступна.", reply_markup=keyboard)
                logger.error(f"Неверный topic_id {topic_id} для канала {channel_name} от @{message.from_user.username}")
                return
            await conn.execute(
                "UPDATE notification_channels SET topic_id = $1 WHERE channel_id = $2",
                topic_id, channel_id
            )
        await message.answer(f"Канал/группа {channel_name} обновлена.", reply_markup=keyboard)
        logger.info(f"Канал/группа {channel_name} (ID: {channel_id}) обновлена с topic_id {topic_id} пользователем @{message.from_user.username}")
        await state.clear()
    except ValueError:
        await message.answer("Введите корректный topic_id или оставьте поле пустым.", reply_markup=keyboard)
        logger.error(f"Неверный формат topic_id {message.text} для канала ID {channel_id} от @{message.from_user.username}")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
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