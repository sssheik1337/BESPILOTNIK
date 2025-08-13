from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_admin_panel_menu, get_remove_channel_menu, get_edit_channel_menu, get_employee_list_menu, get_my_appeals_menu, get_exam_menu
from database.db import add_admin, add_notification_channel, get_notification_channels, get_admins, get_assigned_appeals, get_defect_reports, add_exam_record, get_exam_records, add_defect_report
from config import MAIN_ADMIN_IDS, TOKEN
from datetime import datetime
import logging
from aiogram.exceptions import TelegramBadRequest
from io import BytesIO
import pandas as pd
import json
from utils.validators import validate_media
from utils.statuses import APPEAL_STATUSES

logger = logging.getLogger(__name__)

router = Router()

class AdminResponse(StatesGroup):
    add_channel = State()
    edit_channel = State()
    add_employee = State()
    defect_report_serial = State()
    defect_report_location = State()
    defect_report_media = State()
    defect_status_serial = State()
    exam_fio = State()
    exam_subdivision = State()
    exam_military_unit = State()
    exam_callsign = State()
    exam_specialty = State()
    exam_contact = State()
    exam_video = State()
    exam_photo = State()
    report_serial_from = State()
    report_serial_to = State()

@router.callback_query(F.data == "exam_menu")
async def exam_menu_prompt(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    await callback.message.edit_text("Меню экзаменов:", reply_markup=get_exam_menu())
    logger.info(f"Открыто меню экзаменов пользователем @{callback.from_user.username}")
    await callback.answer()



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
        status_display = APPEAL_STATUSES.get(count['status'], count['status'])  # Используем словарь для перевода
        response += f"{status_display}: {count['total']}\n"
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
        logger.info(f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен пользователям @{message.from_user.username}")
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

@router.callback_query(F.data == "check_employee_appeals")
async def check_employee_appeals(callback: CallbackQuery, **data):
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
        logger.warning(f"Попытка проверки заявок сотрудников от неадминистратора @{callback.from_user.username}")
        return
    admins = await get_admins()
    if not admins:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Список сотрудников пуст.", reply_markup=keyboard)
        logger.info(f"Нет сотрудников для проверки, запрос от @{callback.from_user.username}")
        return
    await callback.message.edit_text("Выберите сотрудника для проверки заявок:", reply_markup=get_employee_list_menu(admins))
    logger.info(f"Запрос проверки заявок сотрудников от @{callback.from_user.username}")

@router.callback_query(F.data.startswith("view_employee_appeals_"))
async def view_employee_appeals(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="check_employee_appeals")]
        ]))
        return
    admin_id = int(callback.data.split("_")[-1])
    appeals, total = await get_assigned_appeals(admin_id, page=0)
    if not appeals:
        await callback.message.edit_text("У сотрудника нет заявок.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="check_employee_appeals")]
        ]))
        logger.info(f"Нет заявок для сотрудника ID {admin_id} по запросу от @{callback.from_user.username}")
        return
    keyboard = get_my_appeals_menu(appeals, page=0, total_appeals=total)  # Используем напрямую
    await callback.message.edit_text(f"Заявки сотрудника (страница 1 из {max(1, (total + 9) // 10)}):", reply_markup=keyboard)
    await state.update_data(admin_id=admin_id, appeals=appeals, total=total, page=0)
    logger.info(f"Показана страница 0 заявок сотрудника ID {admin_id} пользователю @{callback.from_user.username}")
    await callback.answer()

@router.callback_query(F.data == "export_defect_reports")
async def export_defect_reports_prompt(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.edit_text("Введите диапазон серийных номеров (от <from> до <to>) или конкретный серийный номер:", reply_markup=keyboard)
    await state.set_state(AdminResponse.report_serial_from)
    logger.debug(f"Запрос выгрузки отчётов от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.report_serial_from))
async def process_report_serial_from(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    text = message.text.strip()
    if ' ' in text:
        parts = text.split()
        if len(parts) == 3 and parts[1] == 'до':
            serial_from = parts[0]
            serial_to = parts[2]
            await state.update_data(serial_from=serial_from, serial_to=serial_to)
        else:
            await state.update_data(serial=text)
    else:
        await state.update_data(serial=text)
    await state.clear()
    await process_export_defect_reports(message, state, db_pool=db_pool)
    logger.debug(f"Диапазон серийных номеров введён: {text} от @{message.from_user.username}")

async def process_export_defect_reports(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    data_state = await state.get_data()
    serial = data_state.get("serial")
    serial_from = data_state.get("serial_from")
    serial_to = data_state.get("serial_to")
    reports = await get_defect_reports(serial, serial_from, serial_to)
    if not reports:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        await message.answer("Нет отчётов для указанного диапазона/номера.", reply_markup=keyboard)
        logger.warning(f"Нет отчётов для диапазона {serial_from}-{serial_to} или номера {serial}, запрос от @{message.from_user.username}")
        return
    data = []
    for report in reports:
        media_links = json.loads(report['media_links'] or "[]")
        photo_links = [media['file_id'] for media in media_links if media['type'] == "photo"]
        video_links = [media['file_id'] for media in media_links if media['type'] in ["video", "video_note"]]
        data.append({
            'Serial': report['serial'],
            'Дата': report['report_date'],
            'Время': report['report_time'],
            'Место': report['location'],
            'Сотрудник ID': report['employee_id'],
            'Фото': ', '.join(photo_links),
            'Видео': ', '.join(video_links)
        })
    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await message.answer_document(
        document=BufferedInputFile(output.getvalue(), filename="defect_reports.xlsx"),
        reply_markup=keyboard
    )
    logger.info(f"Выгрузка отчётов о неисправности выполнена пользователем @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.defect_report_serial))
async def process_defect_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ])
        await message.answer("Серийный номер не может быть пустым. Попробуйте снова:", reply_markup=keyboard)
        logger.warning(f"Пустой серийный номер для отчёта о дефекте от @{message.from_user.username}")
        return
    await state.update_data(serial=serial)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await message.answer("Введите место:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_report_location)
    logger.debug(f"Серийный номер {serial} для отчёта о дефекте принят от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.defect_report_location))
async def process_defect_location(message: Message, state: FSMContext):
    location = message.text.strip()
    if not location:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ])
        await message.answer("Место не может быть пустым. Попробуйте снова:", reply_markup=keyboard)
        logger.warning(f"Пустое место для отчёта о дефекте от @{message.from_user.username}")
        return
    await state.update_data(location=location)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data="done_defect_media")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await message.answer("Прикрепите фото/видео (до 10, или нажмите 'Готово'):", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_report_media)
    await state.update_data(media_links=[])
    logger.debug(f"Место {location} для отчёта о дефекте принято от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.defect_report_media))
async def process_defect_media(message: Message, state: FSMContext):
    data_state = await state.get_data()
    media_links = data_state.get("media_links", [])
    if len(media_links) >= 10:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_defect_media")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ])
        await message.answer("Достигнуто максимальное количество медиа (10). Нажмите 'Готово'.", reply_markup=keyboard)
        logger.warning(f"Достигнуто максимальное количество медиа для отчёта о дефекте от @{message.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data="done_defect_media")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    is_valid, media = validate_media(message)
    if is_valid:
        file_id = media[0]['file_id']
        file = await message.bot.get_file(file_id)
        file_path = file.file_path
        full_link = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        media[0]['file_id'] = full_link
        media_links.append(media[0])
        await state.update_data(media_links=media_links)
        await message.answer(f"Медиа добавлено ({len(media_links)}/10). Приложите ещё или нажмите 'Готово':", reply_markup=keyboard)
        logger.debug(f"Медиа ({media[0]['type']}) добавлено для отчёта о дефекте от @{message.from_user.username}: {full_link}")
    else:
        await message.answer("Неподдерживаемый формат. Приложите фото (png/jpeg) или видео (mp4).", reply_markup=keyboard)
        logger.warning(f"Неподдерживаемый формат медиа для отчёта о дефекте от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.defect_status_serial))
async def process_defect_status_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ])
        await message.answer("Серийный номер не может быть пустым. Попробуйте снова:", reply_markup=keyboard)
        logger.warning(f"Пустой серийный номер для изменения статуса от @{message.from_user.username}")
        return
    await state.update_data(serial=serial)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Брак", callback_data="set_defect_brak")],
        [InlineKeyboardButton(text="Возврат", callback_data="set_defect_vozvrat")],
        [InlineKeyboardButton(text="Замена", callback_data="set_defect_zamena")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await message.answer("Выберите статус:", reply_markup=keyboard)
    logger.debug(f"Серийный номер {serial} для изменения статуса принят от @{message.from_user.username}")

@router.callback_query(F.data.startswith("set_defect_"))
async def set_defect_status(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    data_state = await state.get_data()
    serial = data_state.get("serial")
    status = callback.data.split("_")[-1]  # brak, vozvrat, zamena
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE serials SET status = $1 WHERE serial = $2",
            status, serial
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await callback.message.edit_text(f"Статус устройства {serial} изменён на '{status}'.", reply_markup=keyboard)
    logger.info(f"Статус устройства {serial} изменён на '{status}' пользователем @{callback.from_user.username}")
    await state.clear()

@router.callback_query(F.data == "take_exam")
async def take_exam_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка принятия экзамена от неадминистратора @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Введите ФИО:", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_fio)
    logger.debug(f"Запрос принятия экзамена от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.exam_fio))
async def process_exam_fio(message: Message, state: FSMContext):
    fio = message.text.strip()
    await state.update_data(fio=fio)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await message.answer("Введите подразделение:", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_subdivision)
    logger.debug(f"ФИО введено: {fio} от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.exam_subdivision))
async def process_exam_subdivision(message: Message, state: FSMContext):
    subdivision = message.text.strip()
    await state.update_data(subdivision=subdivision)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await message.answer("Введите В/Ч:", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_military_unit)
    logger.debug(f"Подразделение введено: {subdivision} от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.exam_military_unit))
async def process_exam_military_unit(message: Message, state: FSMContext):
    military_unit = message.text.strip()
    await state.update_data(military_unit=military_unit)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await message.answer("Введите позывной:", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_callsign)
    logger.debug(f"В/Ч введено: {military_unit} от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.exam_callsign))
async def process_exam_callsign(message: Message, state: FSMContext):
    callsign = message.text.strip()
    await state.update_data(callsign=callsign)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await message.answer("Введите специальность:", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_specialty)
    logger.debug(f"Позывной введён: {callsign} от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.exam_specialty))
async def process_exam_specialty(message: Message, state: FSMContext):
    specialty = message.text.strip()
    await state.update_data(specialty=specialty)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await message.answer("Введите контакт:", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_contact)
    logger.debug(f"Специальность введена: {specialty} от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.exam_contact))
async def process_exam_contact(message: Message, state: FSMContext):
    contact = message.text.strip()
    await state.update_data(contact=contact)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data="done_exam_video")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await message.answer("Прикрепите видео материал (или 'Готово'):", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_video)
    logger.debug(f"Контакт введён: {contact} от @{message.from_user.username}")

@router.message(StateFilter(AdminResponse.exam_video))
async def process_exam_video(message: Message, state: FSMContext):
    if message.video:
        file_id = message.video.file_id
        file = await message.bot.get_file(file_id)
        file_path = file.file_path
        video_link = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        await state.update_data(video_link=video_link)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_exam_photo")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        await message.answer("Прикрепите фото экзаменационного листа (до 10, или 'Готово'):", reply_markup=keyboard)
        await state.set_state(AdminResponse.exam_photo)
        await state.update_data(photo_links=[])
        logger.debug(f"Видео добавлено для экзамена от @{message.from_user.username}: {video_link}")
    else:
        await message.answer("Прикрепите видео или нажмите 'Готово' для пропуска.")
        logger.warning(f"Неверный формат видео от @{message.from_user.username}")

@router.callback_query(F.data == "done_exam_video")
async def skip_exam_video(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data="done_exam_photo")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.edit_text("Прикрепите фото экзаменационного листа (до 10, или 'Готово'):", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_photo)
    await state.update_data(photo_links=[])
    logger.debug(f"Видео пропущено для экзамена от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.exam_photo))
async def process_exam_photo(message: Message, state: FSMContext):
    data_state = await state.get_data()
    photo_links = data_state.get("photo_links", [])
    if len(photo_links) >= 10:
        await message.answer("Достигнуто максимальное количество фото (10). Нажмите 'Готово'.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_exam_photo")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готово", callback_data="done_exam_photo")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    is_valid, media = validate_media(message)
    if is_valid and media[0]['type'] == "photo":
        file_id = media[0]['file_id']
        file = await message.bot.get_file(file_id)
        file_path = file.file_path
        full_link = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        photo_links.append(full_link)
        await state.update_data(photo_links=photo_links)
        await message.answer(f"Фото добавлено ({len(photo_links)}/10). Приложите ещё или нажмите 'Готово':", reply_markup=keyboard)
        logger.debug(f"Фото добавлено для экзамена от @{message.from_user.username}: {full_link}")
    else:
        await message.answer("Неподдерживаемый формат. Приложите фото (png/jpeg).", reply_markup=keyboard)
        logger.warning(f"Неподдерживаемый формат для фото экзамена от @{message.from_user.username}")

@router.callback_query(F.data == "done_exam_photo")
async def skip_exam_photo(callback: CallbackQuery, state: FSMContext):
    data_state = await state.get_data()
    fio = data_state.get("fio", "Не указано")
    subdivision = data_state.get("subdivision", "Не указано")
    military_unit = data_state.get("military_unit", "Не указано")
    callsign = data_state.get("callsign", "Не указано")
    specialty = data_state.get("specialty", "Не указано")
    contact = data_state.get("contact", "Не указано")
    video_link = data_state.get("video_link", "Отсутствует")
    photo_links = data_state.get("photo_links", [])
    text = (f"Предпросмотр экзамена:\n"
            f"ФИО: {fio}\n"
            f"Подразделение: {subdivision}\n"
            f"В/Ч: {military_unit}\n"
            f"Позывной: {callsign}\n"
            f"Специальность: {specialty}\n"
            f"Контакт: {contact}\n"
            f"Видео: {video_link}\n"
            f"Фото: {len(photo_links)} шт.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить", callback_data="submit_exam")],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_exam")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    logger.debug(f"Предпросмотр экзамена: ФИО {fio}, видео {video_link}, фото {len(photo_links)} от @{callback.from_user.username}")

@router.callback_query(F.data == "cancel_exam")
async def cancel_exam(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.edit_text("Приём экзамена отменён.", reply_markup=keyboard)
    logger.info(f"Приём экзамена отменён пользователем @{callback.from_user.username}")

@router.callback_query(F.data == "submit_exam")
async def submit_exam(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    data_state = await state.get_data()
    fio = data_state.get("fio", "")
    subdivision = data_state.get("subdivision", "")
    military_unit = data_state.get("military_unit", "")
    callsign = data_state.get("callsign", "")
    specialty = data_state.get("specialty", "")
    contact = data_state.get("contact", "")
    video_link = data_state.get("video_link", "")
    photo_links = data_state.get("photo_links", [])
    await add_exam_record(fio, subdivision, military_unit, callsign, specialty, contact, video_link, photo_links)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.edit_text("Экзамен принят.", reply_markup=keyboard)
    logger.info(f"Экзамен принят от @{callback.from_user.username}")
    await state.clear()

@router.callback_query(F.data == "export_exams")
async def export_exams_handler(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.delete()
        await callback.message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    records = await get_exam_records()
    if not records:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        await callback.message.delete()
        await callback.message.answer("Нет данных для выгрузки.", reply_markup=keyboard)
        logger.warning(f"Нет данных для выгрузки экзаменов, запрос от @{callback.from_user.username}")
        return
    data = []
    for record in records:
        photo_links = json.loads(record['photo_links'] or "[]")
        data.append({
            'ФИО': record['fio'],
            'Подразделение': record['subdivision'],
            'В/Ч': record['military_unit'],
            'Позывной': record['callsign'],
            'Специальность': record['specialty'],
            'Контакт': record['contact'],
            'Видео': record['video_link'] or 'Отсутствует',
            'Фото': ', '.join(photo_links)
        })
    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.delete()
    await callback.message.answer_document(
        document=BufferedInputFile(output.getvalue(), filename="exam_records.xlsx"),
        reply_markup=keyboard
    )
    logger.info(f"Выгрузка экзаменов выполнена пользователем @{callback.from_user.username}")

@router.callback_query(F.data == "change_defect_status")
async def change_defect_status_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ])
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(f"Попытка изменения статуса устройства от неадминистратора @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await callback.message.edit_text("Введите серийный номер:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_status_serial)
    logger.debug(f"Запрос изменения статуса устройства от @{callback.from_user.username}")

@router.message(StateFilter(AdminResponse.defect_status_serial))
async def process_defect_status_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ])
        await message.answer("Серийный номер не может быть пустым. Попробуйте снова:", reply_markup=keyboard)
        logger.warning(f"Пустой серийный номер для изменения статуса от @{message.from_user.username}")
        return
    await state.update_data(serial=serial)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Брак", callback_data="set_defect_brak")],
        [InlineKeyboardButton(text="Возврат", callback_data="set_defect_vozvrat")],
        [InlineKeyboardButton(text="Замена", callback_data="set_defect_zamena")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await message.answer("Выберите статус:", reply_markup=keyboard)
    logger.debug(f"Серийный номер {serial} для изменения статуса принят от @{message.from_user.username}")

@router.callback_query(F.data.startswith("set_defect_"))
async def set_defect_status(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]))
        return
    data_state = await state.get_data()
    serial = data_state.get("serial")
    status = callback.data.split("_")[-1]  # brak, vozvrat, zamena
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE serials SET status = $1 WHERE serial = $2",
            status, serial
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await callback.message.edit_text(f"Статус устройства {serial} изменён на '{status}'.", reply_markup=keyboard)
    logger.info(f"Статус устройства {serial} изменён на '{status}' пользователем @{callback.from_user.username}")
    await state.clear()

@router.callback_query(F.data == "defect_menu")
async def defect_menu_prompt(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
    async with db_pool.acquire() as conn:
        admin_exists = await conn.fetchval("SELECT 1 FROM admins WHERE admin_id = $1", callback.from_user.id)
        if not admin_exists and callback.from_user.id not in MAIN_ADMIN_IDS:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ])
            await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
            logger.warning(f"Попытка доступа к меню брака от неадминистратора @{callback.from_user.username} (ID {callback.from_user.id})")
            return
        if not admin_exists and callback.from_user.id in MAIN_ADMIN_IDS:
            await add_admin(callback.from_user.id, callback.from_user.username or "unknown")
            logger.info(f"Автоматически добавлен администратор ID {callback.from_user.id} (@{callback.from_user.username})")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить отчёт о неисправности", callback_data="add_defect_report")],
        [InlineKeyboardButton(text="Изменить статус устройства", callback_data="change_defect_status")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    await callback.message.edit_text("Меню брак/возврат/замена:", reply_markup=keyboard)
    logger.debug(f"Открыто меню брака от @{callback.from_user.username}")

@router.callback_query(F.data == "add_defect_report")
async def defect_report_prompt(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]))
        return
    async with db_pool.acquire() as conn:
        admin_exists = await conn.fetchval("SELECT 1 FROM admins WHERE admin_id = $1", callback.from_user.id)
        if not admin_exists and callback.from_user.id not in MAIN_ADMIN_IDS:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ])
            await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
            logger.warning(f"Попытка добавления отчёта о дефекте от неадминистратора @{callback.from_user.username} (ID {callback.from_user.id})")
            return
        if not admin_exists and callback.from_user.id in MAIN_ADMIN_IDS:
            await add_admin(callback.from_user.id, callback.from_user.username or "unknown")
            logger.info(f"Автоматически добавлен администратор ID {callback.from_user.id} (@{callback.from_user.username})")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await callback.message.edit_text("Введите серийный номер:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_report_serial)
    logger.debug(f"Запрос добавления отчёта о дефекте от @{callback.from_user.username}")

@router.callback_query(F.data == "change_defect_status")
async def change_defect_status_prompt(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]))
        return
    async with db_pool.acquire() as conn:
        admin_exists = await conn.fetchval("SELECT 1 FROM admins WHERE admin_id = $1", callback.from_user.id)
        if not admin_exists and callback.from_user.id not in MAIN_ADMIN_IDS:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ])
            await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
            logger.warning(f"Попытка изменения статуса устройства от неадминистратора @{callback.from_user.username} (ID {callback.from_user.id})")
            return
        if not admin_exists and callback.from_user.id in MAIN_ADMIN_IDS:
            await add_admin(callback.from_user.id, callback.from_user.username or "unknown")
            logger.info(f"Автоматически добавлен администратор ID {callback.from_user.id} (@{callback.from_user.username})")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
    ])
    await callback.message.edit_text("Введите серийный номер:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_status_serial)
    logger.debug(f"Запрос изменения статуса устройства от @{callback.from_user.username}")

@router.callback_query(F.data == "done_defect_media")
async def done_defect_media(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]))
        return
    data_state = await state.get_data()
    serial = data_state.get("serial")
    location = data_state.get("location")  # Получаем location из состояния
    report_date = datetime.now().strftime("%Y-%m-%d")
    report_time = datetime.now().strftime("%H:%M")
    media_links = data_state.get("media_links", [])
    employee_id = callback.from_user.id
    try:
        async with db_pool.acquire() as conn:
            admin_exists = await conn.fetchval("SELECT 1 FROM admins WHERE admin_id = $1", employee_id)
            if not admin_exists and employee_id in MAIN_ADMIN_IDS:
                await add_admin(employee_id, callback.from_user.username or "unknown")
                logger.info(f"Автоматически добавлен администратор ID {employee_id} (@{callback.from_user.username})")
            elif not admin_exists:
                await callback.message.edit_text("Вы не зарегистрированы как администратор.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
                ]))
                logger.warning(f"Попытка добавления отчёта о дефекте от незарегистрированного администратора ID {employee_id}")
                return
            await add_defect_report(serial, report_date, report_time, location, json.dumps(media_links), employee_id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ])
        await callback.message.edit_text("Отчёт о дефекте сохранён.", reply_markup=keyboard)
        logger.info(f"Отчёт о дефекте для серийника {serial} сохранён пользователем @{callback.from_user.username}")
    except Exception as e:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ])
        await callback.message.edit_text(f"Ошибка сохранения отчёта: {str(e)}", reply_markup=keyboard)
        logger.error(f"Ошибка сохранения отчёта о дефекте для серийника {serial}: {str(e)}")
    await state.clear()

@router.callback_query(F.data.startswith("employee_appeals_page_"))
async def navigate_employee_appeals_page(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="check_employee_appeals")]
        ]))
        return
    page = int(callback.data.split("_")[-1])
    data_state = await state.get_data()
    admin_id = data_state.get("admin_id")
    appeals = data_state.get("appeals")
    total = data_state.get("total")
    if not appeals or total is None:
        appeals, total = await get_assigned_appeals(admin_id, page=page)
        await state.update_data(appeals=appeals, total=total)
    start_idx = page * 10
    end_idx = min(start_idx + 10, len(appeals))
    page_appeals = appeals[start_idx:end_idx]
    if not page_appeals:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="check_employee_appeals")]
        ])
        await callback.message.edit_text("Нет заявок сотрудника.", reply_markup=keyboard)
        logger.info(f"Нет заявок для сотрудника ID {admin_id} на странице {page} для @{callback.from_user.username}")
        return
    keyboard = get_my_appeals_menu(page_appeals, page, total)  # Используем напрямую
    await callback.message.edit_text(f"Заявки сотрудника (страница {page + 1} из {max(1, (total + 9) // 10)}):", reply_markup=keyboard)
    await state.update_data(page=page)
    logger.info(f"Показана страница {page} заявок сотрудника ID {admin_id} пользователю @{callback.from_user.username}")
    await callback.answer()