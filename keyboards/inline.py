from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import MAIN_ADMIN_IDS

def get_user_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Создать обращение", callback_data="create_appeal")],
        [InlineKeyboardButton(text="📜 История по серийнику", callback_data="serial_history")],
        [InlineKeyboardButton(text="📋 Мои обращения", callback_data="my_appeals_user")]
    ])

def get_admin_menu(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Открытые заявки", callback_data="open_appeals")],
        [InlineKeyboardButton(text="📋 Мои заявки", callback_data="my_appeals")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🔧 Управление базой", callback_data="manage_base")],
        [InlineKeyboardButton(text="🔐 Админ-панель", callback_data="admin_panel")]
    ])

def get_my_appeals_user_menu(appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} ({appeal['status']})",
                callback_data=f"view_appeal_user_{appeal['appeal_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_open_appeals_menu(appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} ({appeal['status']})",
                callback_data=f"view_appeal_{appeal['appeal_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_my_appeals_menu(appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} ({appeal['status']})",
                callback_data=f"view_appeal_{appeal['appeal_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_appeal_actions_menu(appeal_id, status):
    keyboard = []
    if status in ["new", "postponed", "overdue"]:
        keyboard.append([InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"take_appeal_{appeal_id}")])
    if status in ["in_progress"]:
        keyboard.extend([
            [InlineKeyboardButton(text="📝 Ответить", callback_data=f"respond_appeal_{appeal_id}")],
            [InlineKeyboardButton(text="🔄 Делегировать", callback_data=f"delegate_appeal_{appeal_id}")]
        ])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="open_appeals")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_notification_menu(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Взять в работу", callback_data=f"take_appeal_{appeal_id}")],
        [InlineKeyboardButton(text="⏳ Отложить", callback_data=f"postpone_appeal_{appeal_id}")]
    ])

def get_response_menu(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}")]
    ])

def get_base_management_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Импорт серийников", callback_data="import_serials")],
        [InlineKeyboardButton(text="📥 Экспорт серийников", callback_data="export_serials")],
        [InlineKeyboardButton(text="⚠️ Отметить брак/возврат", callback_data="mark_defect")],
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
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_overdue_menu(appeal_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Установить новое время", callback_data=f"set_new_time_{appeal_id}")],
        [InlineKeyboardButton(text="👷 Требуется выезд", callback_data=f"await_specialist_{appeal_id}")]
    ])