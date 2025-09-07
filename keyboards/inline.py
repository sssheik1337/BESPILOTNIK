from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import MAIN_ADMIN_IDS
from utils.statuses import APPEAL_STATUSES
import logging

logger = logging.getLogger(__name__)

def get_user_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Связь с орнитологом", callback_data="create_appeal")],
        [InlineKeyboardButton(text="📋 Мои обращения", callback_data="my_appeals_user")],
        [InlineKeyboardButton(text="🚀 Подготовка к запуску", callback_data="prepare_launch")],
        [InlineKeyboardButton(text="🎮 Настройка пульта", callback_data="setup_remote")],
        [InlineKeyboardButton(text="🛠 Настройка НСУ", callback_data="setup_nsu")]
    ])
    logger.debug("Создана клавиатура для пользовательского меню")
    return keyboard

def get_manuals_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Настройка пульта", callback_data="manual_remote")],
        [InlineKeyboardButton(text="Прошивка ЕРЛС", callback_data="manual_erlc")],
        [InlineKeyboardButton(text="Настройка НСУ", callback_data="manual_nsu")],
        [InlineKeyboardButton(text="Руководство по дрону", callback_data="manual_drone")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    logger.debug("Создана клавиатура меню руководств")
    return keyboard

def get_exam_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Принять экзамен", callback_data="take_exam")],
        [InlineKeyboardButton(text="Выгрузка экзаменов", callback_data="export_exams")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])
    logger.debug("Создана клавиатура для меню экзаменов")
    return keyboard

def get_admin_menu(user_id):
    keyboard = []
    keyboard.append([InlineKeyboardButton(text="📋 Открытые заявки", callback_data="open_appeals")])
    keyboard.append([InlineKeyboardButton(text="🗂️ Закрытые заявки", callback_data="closed_appeals")])
    keyboard.append([InlineKeyboardButton(text="📌 Мои заявки", callback_data="my_appeals")])
    keyboard.append([InlineKeyboardButton(text="📝 Экзамены", callback_data="exam_menu")])
    keyboard.append([InlineKeyboardButton(text="🔍 История по серийнику", callback_data="serial_history")])
    keyboard.append([InlineKeyboardButton(text="🛠 Брак/Возврат/Замена", callback_data="defect_menu")])
    if user_id in MAIN_ADMIN_IDS:
        keyboard.extend([
            [InlineKeyboardButton(text="👨‍💼 Панель администратора", callback_data="admin_panel")]
        ])
    logger.debug(f"Создана клавиатура админского меню для пользователя ID {user_id}")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_my_appeals_user_menu(appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} ({APPEAL_STATUSES.get(appeal['status'], appeal['status'])})",
                callback_data=f"view_appeal_user_{appeal['appeal_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для 'Мои обращения' пользователя с {len(appeals)} заявками")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_open_appeals_menu(appeals, page, total_appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} (Новая)",
                callback_data=f"view_appeal_{appeal['appeal_id']}"
            )
        ])
    nav_buttons = []
    if total_appeals > 10:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"open_appeals_page_{page-1}"))
        if (page + 1) * 10 < total_appeals:
            nav_buttons.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"open_appeals_page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для открытых заявок с {len(appeals)} заявками на странице {page}")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_appeal_actions_menu(appeal_id, status):
    keyboard = []
    if status == 'new':
        keyboard.append([InlineKeyboardButton(text="Взять в работу", callback_data=f"take_appeal_{appeal_id}")])
    else:
        keyboard.extend([
            [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_appeal_{appeal_id}")],
            [InlineKeyboardButton(text="Делегировать", callback_data=f"delegate_appeal_{appeal_id}")],
            [InlineKeyboardButton(text="Требуется выезд", callback_data=f"await_specialist_{appeal_id}")]
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_my_appeals_menu(appeals, page, total_appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} ({APPEAL_STATUSES.get(appeal['status'], appeal['status'])})",
                callback_data=f"view_appeal_{appeal['appeal_id']}"
            )
        ])
    nav_buttons = []
    if total_appeals > 10:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"employee_appeals_page_{page-1}"))
        if (page + 1) * 10 < total_appeals:
            nav_buttons.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"employee_appeals_page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для 'Мои заявки' с {len(appeals)} заявками на странице {page}")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_response_menu(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])

def get_notification_menu(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Взять в работу", callback_data=f"take_appeal_{appeal_id}")]
    ])

def get_channel_take_button(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Взять в работу", callback_data=f"take_appeal_{appeal_id}")]
    ])

def get_base_management_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Импорт серийников", callback_data="import_serials")],
        [InlineKeyboardButton(text="📥 Экспорт серийников", callback_data="export_serials")],
        [InlineKeyboardButton(text="📝 Выгрузка отчётов", callback_data="export_defect_reports")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

def get_admin_panel_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Проверить заявки сотрудников", callback_data="check_employee_appeals")],
        [InlineKeyboardButton(text="📊 Статистика сотрудников", callback_data="stats")],
        [InlineKeyboardButton(text="⚙️ Управление базой", callback_data="manage_base")],
        [InlineKeyboardButton(text="📚 Руководства", callback_data="manage_manuals")],
        [InlineKeyboardButton(text="👤 Добавить сотрудника", callback_data="add_employee")],
        [InlineKeyboardButton(text="📢 Добавить канал/группу", callback_data="add_channel")],
        [InlineKeyboardButton(text="🗑 Удалить канал/группу", callback_data="remove_channel")],
        [InlineKeyboardButton(text="✏️ Изменить канал/группу", callback_data="edit_channel")],
        [InlineKeyboardButton(text="🔑 Изменить кодовое слово", callback_data="change_code_word")],
        [InlineKeyboardButton(text="🏫 Редактировать УТЦ", callback_data="manage_training_centers")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

def get_remove_channel_menu(channels):
    keyboard = []
    for channel in channels:
        topic_part = f"/{channel['topic_id']}" if channel['topic_id'] else ""
        keyboard.append([
            InlineKeyboardButton(
                text=f"{channel['channel_name']}{topic_part}",
                callback_data=f"remove_channel_{channel['channel_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для удаления каналов с {len(channels)} каналами")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_edit_channel_menu(channels):
    keyboard = []
    for channel in channels:
        topic_part = f"/{channel['topic_id']}" if channel['topic_id'] else ""
        keyboard.append([
            InlineKeyboardButton(
                text=f"{channel['channel_name']}{topic_part}",
                callback_data=f"edit_channel_{channel['channel_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для редактирования каналов с {len(channels)} каналами")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_training_centers_menu(centers):
    keyboard = []
    for center in centers:
        if center["center_name"]:  # Проверяем, что center_name не None
            keyboard.append([InlineKeyboardButton(text=center["center_name"], callback_data=f"edit_center_{center['id']}")])
    keyboard.append([InlineKeyboardButton(text="Добавить УТЦ", callback_data="add_training_center")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    logger.debug(f"Создана клавиатура для управления УТЦ с {len(centers)} центрами")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_overdue_menu(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Установить новое время", callback_data=f"set_new_time_{appeal_id}")],
        [InlineKeyboardButton(text="👷 Требуется выезд", callback_data=f"await_specialist_{appeal_id}")]
    ])

def get_defect_status_menu(serial):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Брак", callback_data=f"defect_status_brak_{serial}")],
        [InlineKeyboardButton(text="Возврат", callback_data=f"defect_status_vozvrat_{serial}")],
        [InlineKeyboardButton(text="Замена", callback_data=f"defect_status_zamena_{serial}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

def get_manuals_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Настройка пульта", callback_data="upload_manual_remote")],
        [InlineKeyboardButton(text="Прошивка ЕРЛС", callback_data="upload_manual_erlc")],
        [InlineKeyboardButton(text="Настройка НСУ", callback_data="upload_manual_nsu")],
        [InlineKeyboardButton(text="Руководство по дрону", callback_data="upload_manual_drone")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
    ])

def get_employee_list_menu(admins):
    keyboard = []
    for admin in admins:
        keyboard.append([
            InlineKeyboardButton(
                text=f"@{admin['username']}",
                callback_data=f"view_employee_appeals_{admin['admin_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для списка сотрудников с {len(admins)} админами")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)