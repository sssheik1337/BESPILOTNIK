from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from datetime import datetime
from database.db import (
    get_training_centers,
    add_exam_record,
    validate_exam_record,
    update_exam_record,
)
from config import MAIN_ADMIN_IDS
import logging

logger = logging.getLogger(__name__)

router = Router()


class UserExam(StatesGroup):
    code_word = State()
    fio = State()
    personal_number = State()
    military_unit = State()
    subdivision = State()
    callsign = State()
    specialty = State()
    contact = State()
    training_center = State()
    review = State()


@router.callback_query(F.data == "enroll_training")
async def enroll_training_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите кодовое слово:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        ),
    )
    await state.set_state(UserExam.code_word)
    logger.debug(
        f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) запросил запись на обучение"
    )


@router.message(StateFilter(UserExam.code_word))
async def process_code_word(message: Message, state: FSMContext, **data):
    code_word = message.text.strip()
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
    async with db_pool.acquire() as conn:
        db_code_word = await conn.fetchval(
            "SELECT code_word FROM training_centers WHERE LOWER(code_word) = LOWER($1)",
            code_word,
        )
        logger.debug(f"Запрошено кодовое слово: {db_code_word}")
        if not db_code_word:
            await message.answer(
                "Неверное кодовое слово. Попробуйте снова:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="main_menu"
                            )
                        ]
                    ]
                ),
            )
            logger.warning(
                f"Неверное кодовое слово '{code_word}' от пользователя @{message.from_user.username} (ID: {message.from_user.id})"
            )
            return
    await state.update_data(code_word=code_word)
    await message.answer(
        "⚠️ Внимание!\n"
        "Продолжая использовать бот, вы автоматически соглашаетесь с обработкой ваших персональных данных.\n"
        "Введите ФИО:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        ),
    )
    await state.set_state(UserExam.fio)
    logger.debug(
        f"Кодовое слово {code_word} принято от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.message(StateFilter(UserExam.fio))
async def process_fio(message: Message, state: FSMContext, bot: Bot):
    fio = message.text.strip()
    await state.update_data(fio=fio)
    if await _maybe_return_to_review(message, state):
        return
    await message.answer(
        "Введите личный номер или жетон (например, АВ-449852):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        ),
    )
    await state.set_state(UserExam.personal_number)
    logger.debug(
        f"ФИО {fio} принято от @{message.from_user.username} (ID: {message.from_user.id})"
    )
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(
            f"Сообщение с ФИО удалено для @{message.from_user.username} (ID: {message.from_user.id})"
        )
    except Exception as e:
        logger.error(
            f"Ошибка удаления сообщения с ФИО для @{message.from_user.username}: {str(e)}"
        )


@router.message(StateFilter(UserExam.personal_number))
async def process_personal_number(message: Message, state: FSMContext, bot: Bot):
    personal_number = message.text.strip()
    await state.update_data(personal_number=personal_number)
    if await _maybe_return_to_review(message, state):
        return
    await message.answer(
        "Введите военную часть (например, В/Ч 29657):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        ),
    )
    await state.set_state(UserExam.military_unit)
    logger.debug(
        f"Личный номер {personal_number} принят от @{message.from_user.username} (ID: {message.from_user.id})"
    )
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(
            f"Сообщение с личным номером удалено для @{message.from_user.username} (ID: {message.from_user.id})"
        )
    except Exception as e:
        logger.error(
            f"Ошибка удаления сообщения с личным номером для @{message.from_user.username}: {str(e)}"
        )


@router.message(StateFilter(UserExam.military_unit))
async def process_military_unit(message: Message, state: FSMContext, bot: Bot):
    military_unit = message.text.strip()
    await state.update_data(military_unit=military_unit)
    if await _maybe_return_to_review(message, state):
        return
    await message.answer(
        "Введите подразделение:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        ),
    )
    await state.set_state(UserExam.subdivision)
    logger.debug(
        f"В/Ч {military_unit} принято от @{message.from_user.username} (ID: {message.from_user.id})"
    )
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(
            f"Сообщение с В/Ч удалено для @{message.from_user.username} (ID: {message.from_user.id})"
        )
    except Exception as e:
        logger.error(
            f"Ошибка удаления сообщения с В/Ч для @{message.from_user.username}: {str(e)}"
        )


@router.message(StateFilter(UserExam.subdivision))
async def process_subdivision(message: Message, state: FSMContext, bot: Bot):
    subdivision = message.text.strip()
    await state.update_data(subdivision=subdivision)
    if await _maybe_return_to_review(message, state):
        return
    await message.answer(
        "Введите позывной:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        ),
    )
    await state.set_state(UserExam.callsign)
    logger.debug(
        f"Подразделение {subdivision} принято от @{message.from_user.username} (ID: {message.from_user.id})"
    )
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(
            f"Сообщение с подразделением удалено для @{message.from_user.username} (ID: {message.from_user.id})"
        )
    except Exception as e:
        logger.error(
            f"Ошибка удаления сообщения с подразделением для @{message.from_user.username}: {str(e)}"
        )


@router.message(StateFilter(UserExam.callsign))
async def process_callsign(message: Message, state: FSMContext, bot: Bot):
    callsign = message.text.strip()
    await state.update_data(callsign=callsign)
    if await _maybe_return_to_review(message, state):
        return
    await message.answer(
        "Введите направление (например, \"Север\", \"Юг\", \"Днепр\", \"Покровск\"):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        ),
    )
    await state.set_state(UserExam.specialty)
    logger.debug(
        f"Позывной {callsign} принят от @{message.from_user.username} (ID: {message.from_user.id})"
    )
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(
            f"Сообщение с позывным удалено для @{message.from_user.username} (ID: {message.from_user.id})"
        )
    except Exception as e:
        logger.error(
            f"Ошибка удаления сообщения с позывным для @{message.from_user.username}: {str(e)}"
        )


@router.message(StateFilter(UserExam.specialty))
async def process_specialty(message: Message, state: FSMContext, bot: Bot):
    specialty = message.text.strip()
    await state.update_data(specialty=specialty)
    if await _maybe_return_to_review(message, state):
        return
    await message.answer(
        "Введите контакт для связи в Telegram:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
            ]
        ),
    )
    await state.set_state(UserExam.contact)
    logger.debug(
        f"Направление {specialty} принята от @{message.from_user.username} (ID: {message.from_user.id})"
    )
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        logger.error(
            f"Ошибка удаления сообщения с направлением для @{message.from_user.username}: {str(e)}"
        )


@router.message(StateFilter(UserExam.contact))
async def process_contact(message: Message, state: FSMContext, bot: Bot):
    contact = message.text.strip()
    await state.update_data(contact=contact)
    if await _maybe_return_to_review(message, state):
        return
    await _send_exam_review(message, state)
    await state.set_state(UserExam.review)
    logger.debug(
        f"Контакт {contact} принят от @{message.from_user.username} (ID: {message.from_user.id})"
    )
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(
            f"Сообщение с контактом удалено для @{message.from_user.username} (ID: {message.from_user.id})"
        )
    except Exception as e:
        logger.error(
            f"Ошибка удаления сообщения с контактом для @{message.from_user.username}: {str(e)}"
        )


@router.callback_query(
    F.data.startswith("select_center_"), StateFilter(UserExam.training_center)
)
async def process_training_center(callback: CallbackQuery, state: FSMContext, **data):
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
        await callback.answer()
        return

    user_id = callback.from_user.id
    username = callback.from_user.username or "неизвестно"
    # Проверяем, является ли пользователь админом
    async with db_pool.acquire() as conn:
        is_admin = (
            await conn.fetchval("SELECT 1 FROM admins WHERE admin_id = $1", user_id)
            or user_id in MAIN_ADMIN_IDS
        )
        if is_admin:
            logger.debug(
                f"Пропускаем select_center_ для администратора @{username} (ID: {user_id})"
            )
            await callback.answer()
            return  # Админы обрабатываются в admin_panel.py

    center_id = int(callback.data.split("_")[-1])
    data_state = await state.get_data()
    fio = data_state.get("fio")
    personal_number = data_state.get("personal_number")
    military_unit = data_state.get("military_unit")
    subdivision = data_state.get("subdivision")
    callsign = data_state.get("callsign")
    specialty = data_state.get("specialty")
    contact = data_state.get("contact")
    async with db_pool.acquire() as conn:
        center = await conn.fetchrow(
            "SELECT center_name, chat_link FROM training_centers WHERE id = $1",
            center_id,
        )
        if not center:
            await callback.message.edit_text(
                "УТЦ не найден.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="main_menu"
                            )
                        ]
                    ]
                ),
            )
            logger.warning(f"УТЦ ID {center_id} не найден для @{username}")
            await callback.answer()
            return
        exam_id = await validate_exam_record(
            fio, personal_number, military_unit, subdivision, specialty, contact
        )
        if exam_id:
            await update_exam_record(
                exam_id, None, None
            )  # Пользователь не добавляет медиа
        else:
            now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
            await add_exam_record(
                fio=fio,
                subdivision=subdivision,
                military_unit=military_unit,
                callsign=callsign,
                specialty=specialty,
                contact=contact,
                personal_number=personal_number,
                training_center_id=center_id,
                user_id=user_id,
                application_date=now_str,
            )
        await callback.message.edit_text(
            f"Вы успешно записаны на обучение в {center['center_name']}!\n"
            f"Присоединяйтесь к чату: {center['chat_link']}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Перейти в чат", url=center["chat_link"]
                        )
                    ],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
                ]
            ),
        )
        logger.info(
            f"Пользователь @{username} (ID: {user_id}) записан на обучение в {center['center_name']} (ID: {center_id})"
        )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "exam_review_confirm", StateFilter(UserExam.review))
async def confirm_exam_data(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data при подтверждении записи на обучение")
        await callback.message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]]
            ),
        )
        await callback.answer()
        return

    centers = await get_training_centers()
    if not centers:
        await callback.message.answer(
            "Учебные центры не найдены. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]]
            ),
        )
        logger.warning(
            f"УТЦ не найдены для @{callback.from_user.username} (ID: {callback.from_user.id})"
        )
        await state.clear()
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=center["center_name"],
                    callback_data=f"select_center_{center['id']}",
                )
            ]
            for center in centers
        ]
    )
    keyboard.inline_keyboard.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    )
    await callback.message.answer("Выберите учебный центр:", reply_markup=keyboard)
    await state.set_state(UserExam.training_center)
    await callback.answer()


@router.callback_query(F.data == "exam_review_back")
async def back_to_exam_review(callback: CallbackQuery, state: FSMContext):
    await _send_exam_review(callback.message, state)
    await state.set_state(UserExam.review)
    await callback.answer()


@router.callback_query(F.data.startswith("exam_edit_"), StateFilter(UserExam.review))
async def edit_exam_field(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split("exam_edit_")[-1]
    prompts = {
        "fio": "Введите ФИО:",
        "personal_number": "Введите личный номер или жетон (например, АВ-449852):",
        "military_unit": "Введите военную часть (например, В/Ч 29657):",
        "subdivision": "Введите подразделение:",
        "callsign": "Введите позывной:",
        "specialty": "Введите направление (например, \"Север\", \"Юг\", \"Днепр\", \"Покровск\"):",
        "contact": "Введите контакт для связи в Telegram:",
    }
    target_state = {
        "fio": UserExam.fio,
        "personal_number": UserExam.personal_number,
        "military_unit": UserExam.military_unit,
        "subdivision": UserExam.subdivision,
        "callsign": UserExam.callsign,
        "specialty": UserExam.specialty,
        "contact": UserExam.contact,
    }.get(action)

    if not target_state:
        logger.warning(f"Неизвестное поле редактирования: {action}")
        await callback.answer("Неизвестное поле")
        return

    await state.update_data(return_to_review=True)
    await callback.message.answer(
        prompts[action],
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_review_back")]]
        ),
    )
    await state.set_state(target_state)
    await callback.answer()


async def _send_exam_review(message: Message, state: FSMContext):
    data = await state.get_data()
    text = (
        "Проверьте введенные данные:\n\n"
        f"👤 ФИО: {data.get('fio', '—')}\n"
        f"🎟 Личный номер/жетон: {data.get('personal_number', '—')}\n"
        f"🏢 Военная часть: {data.get('military_unit', '—')}\n"
        f"🏘 Подразделение: {data.get('subdivision', '—')}\n"
        f"📡 Позывной: {data.get('callsign', '—')}\n"
        f"🧭 Направление: {data.get('specialty', '—')}\n"
        f"☎️ Контакт: {data.get('contact', '—')}\n"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="exam_review_confirm")],
            [InlineKeyboardButton(text="✏️ Редактировать ФИО", callback_data="exam_edit_fio")],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать номер/жетон",
                    callback_data="exam_edit_personal_number",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать военную часть",
                    callback_data="exam_edit_military_unit",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать подразделение",
                    callback_data="exam_edit_subdivision",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать позывной",
                    callback_data="exam_edit_callsign",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать направление",
                    callback_data="exam_edit_specialty",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать контакт",
                    callback_data="exam_edit_contact",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="select_scenario")],
        ]
    )
    await message.answer(text, reply_markup=keyboard)


async def _maybe_return_to_review(message: Message, state: FSMContext) -> bool:
    data = await state.get_data()
    if data.get("return_to_review"):
        await state.update_data(return_to_review=False)
        await _send_exam_review(message, state)
        await state.set_state(UserExam.review)
        return True
    return False
