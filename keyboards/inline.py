from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from config import MAIN_ADMIN_IDS
from utils.statuses import APPEAL_STATUSES
import logging

logger = logging.getLogger(__name__)


manual_category_cb = CallbackData("manualcat", "role", "action", "category")
manual_file_cb = CallbackData("manual", "action", "category", "file_id")


def get_user_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📞 Связь с орнитологом", callback_data="create_appeal"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Мои обращения", callback_data="my_appeals_user"
                )
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
        ]
    )
    logger.debug("Создана клавиатура для пользовательского меню")
    return keyboard


def get_manuals_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Настройка пульта",
                    callback_data=manual_category_cb.new(
                        role="user", action="open", category="remote_settings"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧰 Прошивка ЕРЛС",
                    callback_data=manual_category_cb.new(
                        role="user", action="open", category="erls_firmware"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛰 Настройка НСУ",
                    callback_data=manual_category_cb.new(
                        role="user", action="open", category="ncu_setup"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="📘 Руководство по дрону",
                    callback_data=manual_category_cb.new(
                        role="user", action="open", category="drone_guide"
                    ),
                )
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
        ]
    )
    logger.debug("Создана клавиатура меню руководств")
    return keyboard


def get_manual_files_menu(category: str, files, *, is_admin: bool):
    keyboard = []
    for manual_file in files:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=manual_file["file_name"],
                    callback_data=manual_file_cb.new(
                        action="open" if is_admin else "open_user",
                        category=category,
                        file_id=manual_file["id"],
                    ),
                )
            ]
        )

    if is_admin:
        control_row = [
            InlineKeyboardButton(
                text="➕ Добавить файл",
                callback_data=manual_category_cb.new(
                    role="admin", action="add", category=category
                ),
            )
        ]
        if files:
            control_row.append(
                InlineKeyboardButton(
                    text="🗑 Удалить все",
                    callback_data=manual_category_cb.new(
                        role="admin", action="delete_all", category=category
                    ),
                )
            )
        keyboard.append(control_row)

    keyboard.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="manage_manuals" if is_admin else "manuals",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_manual_file_actions(category: str, file_id: int, *, is_admin: bool):
    actions = []
    if is_admin:
        actions.append(
            InlineKeyboardButton(
                text="Удалить файл",
                callback_data=manual_file_cb.new(
                    action="delete_prompt", category=category, file_id=file_id
                ),
            )
        )
    actions.append(
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=manual_category_cb.new(
                role="admin" if is_admin else "user",
                action="open",
                category=category,
            ),
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=[actions])


def get_manual_delete_confirm(category: str, file_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Удалить",
                    callback_data=manual_file_cb.new(
                        action="delete", category=category, file_id=file_id
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Отмена",
                    callback_data=manual_file_cb.new(
                        action="open", category=category, file_id=file_id
                    ),
                )
            ],
        ]
    )


def get_manual_delete_all_confirm(category: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Удалить все",
                    callback_data=manual_category_cb.new(
                        role="admin", action="delete_all_confirm", category=category
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Отмена",
                    callback_data=manual_category_cb.new(
                        role="admin", action="open", category=category
                    ),
                )
            ],
        ]
    )


def get_manual_post_upload_actions(category: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить ещё",
                    callback_data=manual_category_cb.new(
                        role="admin", action="add_more", category=category
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сохранить",
                    callback_data=manual_category_cb.new(
                        role="admin", action="open", category=category
                    ),
                )
            ],
        ]
    )


def get_exam_menu():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Принять экзамен", callback_data="take_exam")],
            [
                InlineKeyboardButton(
                    text="Удалить экзамен", callback_data="delete_exam"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Выгрузка экзаменов", callback_data="export_exams"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )
    logger.debug("Создана клавиатура для меню экзаменов")
    return keyboard


def get_admin_menu(user_id):
    keyboard = []
    keyboard.append(
        [InlineKeyboardButton(text="📋 Открытые заявки", callback_data="open_appeals")]
    )
    keyboard.append(
        [InlineKeyboardButton(text="🗂️ Закрытые заявки", callback_data="closed_appeals")]
    )
    keyboard.append(
        [InlineKeyboardButton(text="📌 Мои заявки", callback_data="my_appeals")]
    )
    keyboard.append(
        [InlineKeyboardButton(text="📝 Экзамены", callback_data="exam_menu")]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                text="🔍 История по серийнику", callback_data="serial_history"
            )
        ]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                text="🛠 Ремонт/Замена", callback_data="defect_menu"
            )
        ]
    )
    keyboard.append(
        [InlineKeyboardButton(text="📋 Учёт визитов", callback_data="manage_visits")]
    )
    if user_id in MAIN_ADMIN_IDS:
        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        text="👨‍💼 Панель администратора", callback_data="admin_panel"
                    )
                ]
            ]
        )
    logger.debug(f"Создана клавиатура админского меню для пользователя ID {user_id}")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_my_appeals_user_menu(appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"Заявка №{appeal['appeal_id']} ({APPEAL_STATUSES.get(appeal['status'], appeal['status'])})",
                    callback_data=f"view_appeal_user_{appeal['appeal_id']}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(
        f"Создана клавиатура для 'Мои обращения' пользователя с {len(appeals)} заявками"
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_user_appeal_actions_menu(
    appeal_id: int, status: str, media_count: int, include_view_button: bool = False
) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    if include_view_button:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="📄 Просмотреть заявку",
                    callback_data=f"view_appeal_user_{appeal_id}",
                )
            ]
        )
    if media_count > 0:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"📸 Медиа ({media_count})",
                    callback_data=f"show_media_user_{appeal_id}",
                )
            ]
        )
    if status != "closed":
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="💬 Ответить", callback_data=f"reply_user_{appeal_id}"
                )
            ]
        )
    if status in ["new", "in_progress"]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="Закрыть заявку",
                    callback_data=f"close_appeal_user_{appeal_id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_open_appeals_menu(appeals, page, total_appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"Заявка №{appeal['appeal_id']} (Новая)",
                    callback_data=f"view_appeal_{appeal['appeal_id']}",
                )
            ]
        )
    nav_buttons = []
    if total_appeals > 10:
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Предыдущая", callback_data=f"open_appeals_page_{page - 1}"
                )
            )
        if (page + 1) * 10 < total_appeals:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Следующая ➡️", callback_data=f"open_appeals_page_{page + 1}"
                )
            )
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(
        f"Создана клавиатура для открытых заявок с {len(appeals)} заявками на странице {page}"
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_appeal_actions_menu(appeal_id, status, can_service: bool = False):
    keyboard = []
    if status == "new":
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="Взять в работу", callback_data=f"take_appeal_{appeal_id}"
                )
            ]
        )
    else:
        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        text="💬 Ответить", callback_data=f"reply_appeal_{appeal_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Делегировать",
                        callback_data=f"delegate_appeal_{appeal_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Требуется выезд",
                        callback_data=f"await_specialist_{appeal_id}",
                    )
                ],
            ]
        )
        if can_service:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text="🔧 Ремонт",
                        callback_data=f"repair_appeal_{appeal_id}",
                    ),
                    InlineKeyboardButton(
                        text="🔁 Замена",
                        callback_data=f"replace_appeal_{appeal_id}",
                    ),
                ]
            )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(
        "Создана клавиатура действий по заявке №%s (статус=%s, сервисные кнопки=%s)",
        appeal_id,
        status,
        can_service,
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_my_appeals_menu(appeals, page, total_appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"Заявка №{appeal['appeal_id']} ({APPEAL_STATUSES.get(appeal['status'], appeal['status'])})",
                    callback_data=f"view_appeal_{appeal['appeal_id']}",
                )
            ]
        )
    nav_buttons = []
    if total_appeals > 10:
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Предыдущая",
                    callback_data=f"employee_appeals_page_{page - 1}",
                )
            )
        if (page + 1) * 10 < total_appeals:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Следующая ➡️",
                    callback_data=f"employee_appeals_page_{page + 1}",
                )
            )
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(
        f"Создана клавиатура для 'Мои заявки' с {len(appeals)} заявками на странице {page}"
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_response_menu(appeal_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить", callback_data=f"reply_appeal_{appeal_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data=f"view_appeal_{appeal_id}"
                )
            ],
        ]
    )


def get_notification_menu(appeal_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Взять в работу", callback_data=f"take_appeal_{appeal_id}"
                )
            ]
        ]
    )


def get_channel_take_button(appeal_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Взять в работу", callback_data=f"take_appeal_{appeal_id}"
                )
            ]
        ]
    )


def get_base_management_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Импорт серийников", callback_data="import_serials"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Экспорт серийников", callback_data="export_serials"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Выгрузка отчётов", callback_data="export_defect_reports"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )


def get_visits_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Начать визит", callback_data="visit_start")],
            [
                InlineKeyboardButton(
                    text="📤 Выгрузить визиты (Excel)",
                    callback_data="visit_export",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )


def get_admin_panel_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👥 Проверить заявки сотрудников",
                    callback_data="check_employee_appeals",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика сотрудников", callback_data="stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Управление базой", callback_data="manage_base"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Руководства", callback_data="manage_manuals"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Добавить сотрудника", callback_data="add_employee"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Добавить канал/группу", callback_data="add_channel"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить канал/группу", callback_data="remove_channel"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить канал/группу", callback_data="edit_channel"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔑 Изменить кодовое слово", callback_data="change_code_word"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏫 Редактировать УТЦ", callback_data="manage_training_centers"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )


def get_remove_channel_menu(channels):
    keyboard = []
    for channel in channels:
        topic_part = f"/{channel['topic_id']}" if channel["topic_id"] else ""
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{channel['channel_name']}{topic_part}",
                    callback_data=f"remove_channel_{channel['channel_id']}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для удаления каналов с {len(channels)} каналами")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_edit_channel_menu(channels):
    keyboard = []
    for channel in channels:
        topic_part = f"/{channel['topic_id']}" if channel["topic_id"] else ""
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{channel['channel_name']}{topic_part}",
                    callback_data=f"edit_channel_{channel['channel_id']}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(
        f"Создана клавиатура для редактирования каналов с {len(channels)} каналами"
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_training_centers_menu(centers):
    keyboard = []
    for center in centers:
        if center["center_name"]:  # Проверяем, что center_name не None
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=center["center_name"],
                        callback_data=f"edit_center_{center['id']}",
                    )
                ]
            )
    keyboard.append(
        [InlineKeyboardButton(text="Добавить УТЦ", callback_data="add_training_center")]
    )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    logger.debug(f"Создана клавиатура для управления УТЦ с {len(centers)} центрами")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_overdue_menu(appeal_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Установить новое время",
                    callback_data=f"set_new_time_{appeal_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👷 Требуется выезд",
                    callback_data=f"await_specialist_{appeal_id}",
                )
            ],
        ]
    )


def get_defect_status_menu(serial):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ремонт", callback_data=f"defect_status_repair_{serial}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Замена", callback_data=f"defect_status_replacement_{serial}"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )


def get_manuals_admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Настройка пульта",
                    callback_data=manual_category_cb.new(
                        role="admin", action="open", category="remote_settings"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Прошивка ЕРЛС",
                    callback_data=manual_category_cb.new(
                        role="admin", action="open", category="erls_firmware"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Настройка НСУ",
                    callback_data=manual_category_cb.new(
                        role="admin", action="open", category="ncu_setup"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Руководство по дрону",
                    callback_data=manual_category_cb.new(
                        role="admin", action="open", category="drone_guide"
                    ),
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")],
        ]
    )


def get_employee_list_menu(admins):
    keyboard = []
    for admin in admins:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"@{admin['username']}",
                    callback_data=f"view_employee_appeals_{admin['admin_id']}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для списка сотрудников с {len(admins)} админами")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
