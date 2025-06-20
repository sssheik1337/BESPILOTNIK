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

def get_admin_menu(user_id):
    keyboard = []
    keyboard.append([InlineKeyboardButton(text="📋 Открытые заявки", callback_data="open_appeals")])
    keyboard.append([InlineKeyboardButton(text="📌 Мои заявки", callback_data="my_appeals")])
    keyboard.append([InlineKeyboardButton(text="🔍 История по серийнику", callback_data="serial_history")])
    keyboard.append([InlineKeyboardButton(text="📊 Статистика", callback_data="stats")])
    keyboard.append([InlineKeyboardButton(text="🗂️ Закрытые заявки", callback_data="closed_appeals")])
    keyboard.append([InlineKeyboardButton(text="🛠 Брак/Возврат/Замена", callback_data="mark_defect")])
    if user_id in MAIN_ADMIN_IDS:
        keyboard.extend([
            [InlineKeyboardButton(text="⚙️ Управление базой", callback_data="manage_base")],
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

def get_open_appeals_menu(appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} ({APPEAL_STATUSES.get(appeal['status'], appeal['status'])})",
                callback_data=f"view_appeal_{appeal['appeal_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для 'Открытые заявки' с {len(appeals)} заявками")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_my_appeals_menu(appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} ({APPEAL_STATUSES.get(appeal['status'], appeal['status'])})",
                callback_data=f"view_appeal_{appeal['appeal_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для 'Мои заявки' с {len(appeals)} заявками")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_appeal_actions_menu(appeal_id, status):
    keyboard = []
    if status in ["new", "postponed", "overdue"]:
        keyboard.append([InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"take_appeal_{appeal_id}")])
    if status in ["in_progress", "awaiting_specialist"]:  # Добавлен awaiting_specialist
        keyboard.extend([
            [InlineKeyboardButton(text="📝 Ответить", callback_data=f"respond_appeal_{appeal_id}")],
            [InlineKeyboardButton(text="🔄 Делегировать", callback_data=f"delegate_appeal_{appeal_id}")],
            [InlineKeyboardButton(text="🔧 Замена устройства", callback_data=f"mark_defect_{appeal_id}")],
            [InlineKeyboardButton(text="💬 Продолжить диалог", callback_data=f"continue_dialogue_{appeal_id}")]
        ])
    if status in ["replacement_process"]:
        keyboard.extend([
            [InlineKeyboardButton(text="🔧 Ввести новый серийный номер", callback_data=f"complete_replacement_{appeal_id}")]
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="my_appeals")])
    logger.debug(f"Создана клавиатура действий для заявки №{appeal_id} со статусом {status}")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_notification_menu(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"take_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="⏳ Отложить", callback_data=f"postpone_appeal_{appeal_id}")]
    ])

def get_channel_take_button(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"take_appeal_{appeal_id}")]
    ])

def get_response_menu(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])

def get_base_management_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Импорт серийников", callback_data="import_serials")],
        [InlineKeyboardButton(text="📥 Экспорт серийников", callback_data="export_serials")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

def get_admin_panel_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Добавить сотрудника", callback_data="add_employee")],
        [InlineKeyboardButton(text="📢 Добавить канал/группу", callback_data="add_channel")],
        [InlineKeyboardButton(text="🗑 Удалить канал/группу", callback_data="remove_channel")],
        [InlineKeyboardButton(text="✏️ Изменить канал/группу", callback_data="edit_channel")],
        [InlineKeyboardButton(text="📜 Список каналов/групп", callback_data="list_channels")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])

def get_remove_channel_menu(channels):
    keyboard = []
    for channel in channels:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{channel['channel_name']}{f'/{channel['topic_id']}' if channel['topic_id'] else ''}",
                callback_data=f"remove_channel_{channel['channel_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для удаления каналов с {len(channels)} каналами")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_edit_channel_menu(channels):
    keyboard = []
    for channel in channels:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{channel['channel_name']}{f'/{channel['topic_id']}' if channel['topic_id'] else ''}",
                callback_data=f"edit_channel_{channel['channel_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для редактирования каналов с {len(channels)} каналами")
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