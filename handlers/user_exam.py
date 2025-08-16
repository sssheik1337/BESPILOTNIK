from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from database.db import get_code_word, get_training_centers, add_exam_record, validate_exam_record, update_exam_record
from config import TOKEN
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

@router.callback_query(F.data == "enroll_training")
async def enroll_training_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите кодовое слово:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    ]))
    await state.set_state(UserExam.code_word)
    logger.debug(f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) запросил запись на обучение")

@router.message(StateFilter(UserExam.code_word))
async def process_code_word(message: Message, state: FSMContext, bot: Bot):
    code_word = message.text.strip()
    db_code_word = await get_code_word()
    if code_word.lower() != db_code_word.lower():
        await message.answer("Некорректное кодовое слово. Попробуйте снова:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
        ]))
        logger.warning(f"Некорректное кодовое слово {code_word} от @{message.from_user.username} (ID: {message.from_user.id})")
        return
    await state.update_data(code_word=code_word)
    await message.answer("Введите ФИО:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    ]))
    await state.set_state(UserExam.fio)
    logger.debug(f"Кодовое слово подтверждено для @{message.from_user.username} (ID: {message.from_user.id})")
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(f"Сообщение с кодовым словом удалено для @{message.from_user.username} (ID: {message.from_user.id})")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения с кодовым словом для @{message.from_user.username}: {str(e)}")

@router.message(StateFilter(UserExam.fio))
async def process_fio(message: Message, state: FSMContext, bot: Bot):
    fio = message.text.strip()
    await state.update_data(fio=fio)
    await message.answer("Введите личный номер или жетон (например, АВ-449852):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    ]))
    await state.set_state(UserExam.personal_number)
    logger.debug(f"ФИО {fio} принято от @{message.from_user.username} (ID: {message.from_user.id})")
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(f"Сообщение с ФИО удалено для @{message.from_user.username} (ID: {message.from_user.id})")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения с ФИО для @{message.from_user.username}: {str(e)}")

@router.message(StateFilter(UserExam.personal_number))
async def process_personal_number(message: Message, state: FSMContext, bot: Bot):
    personal_number = message.text.strip()
    await state.update_data(personal_number=personal_number)
    await message.answer("Введите военную часть (например, В/Ч 29657):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    ]))
    await state.set_state(UserExam.military_unit)
    logger.debug(f"Личный номер {personal_number} принят от @{message.from_user.username} (ID: {message.from_user.id})")
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(f"Сообщение с личным номером удалено для @{message.from_user.username} (ID: {message.from_user.id})")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения с личным номером для @{message.from_user.username}: {str(e)}")

@router.message(StateFilter(UserExam.military_unit))
async def process_military_unit(message: Message, state: FSMContext, bot: Bot):
    military_unit = message.text.strip()
    await state.update_data(military_unit=military_unit)
    await message.answer("Введите подразделение:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    ]))
    await state.set_state(UserExam.subdivision)
    logger.debug(f"В/Ч {military_unit} принято от @{message.from_user.username} (ID: {message.from_user.id})")
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(f"Сообщение с В/Ч удалено для @{message.from_user.username} (ID: {message.from_user.id})")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения с В/Ч для @{message.from_user.username}: {str(e)}")

@router.message(StateFilter(UserExam.subdivision))
async def process_subdivision(message: Message, state: FSMContext, bot: Bot):
    subdivision = message.text.strip()
    await state.update_data(subdivision=subdivision)
    await message.answer("Введите позывной:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    ]))
    await state.set_state(UserExam.callsign)
    logger.debug(f"Подразделение {subdivision} принято от @{message.from_user.username} (ID: {message.from_user.id})")
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(f"Сообщение с подразделением удалено для @{message.from_user.username} (ID: {message.from_user.id})")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения с подразделением для @{message.from_user.username}: {str(e)}")

@router.message(StateFilter(UserExam.callsign))
async def process_callsign(message: Message, state: FSMContext, bot: Bot):
    callsign = message.text.strip()
    await state.update_data(callsign=callsign)
    await message.answer("Введите специальность:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    ]))
    await state.set_state(UserExam.specialty)
    logger.debug(f"Позывной {callsign} принят от @{message.from_user.username} (ID: {message.from_user.id})")
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(f"Сообщение с позывным удалено для @{message.from_user.username} (ID: {message.from_user.id})")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения с позывным для @{message.from_user.username}: {str(e)}")

@router.message(StateFilter(UserExam.specialty))
async def process_specialty(message: Message, state: FSMContext, bot: Bot):
    specialty = message.text.strip()
    await state.update_data(specialty=specialty)
    await message.answer("Введите контакт для связи в Telegram:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")]
    ]))
    await state.set_state(UserExam.contact)
    logger.debug(f"Специальность {specialty} принята от @{message.from_user.username} (ID: {message.from_user.id})")
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(f"Сообщение со специальностью удалено для @{message.from_user.username} (ID: {message.from_user.id})")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения со специальностью для @{message.from_user.username}: {str(e)}")

@router.message(StateFilter(UserExam.contact))
async def process_contact(message: Message, state: FSMContext, bot: Bot):
    contact = message.text.strip()
    await state.update_data(contact=contact)
    centers = await get_training_centers()
    if not centers:
        await message.answer("Учебные центры не найдены. Обратитесь к администратору.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        logger.warning(f"УТЦ не найдены для @{message.from_user.username} (ID: {message.from_user.id})")
        await state.clear()
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
            logger.debug(f"Сообщение с контактом удалено для @{message.from_user.username} (ID: {message.from_user.id})")
        except Exception as e:
            logger.error(f"Ошибка удаления сообщения с контактом для @{message.from_user.username}: {str(e)}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=center["center_name"], callback_data=f"select_center_{center['id']}")]
        for center in centers
    ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="select_scenario")])
    await message.answer("Выберите учебный центр:", reply_markup=keyboard)
    await state.set_state(UserExam.training_center)
    logger.debug(f"Контакт {contact} принят от @{message.from_user.username} (ID: {message.from_user.id})")
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(f"Сообщение с контактом удалено для @{message.from_user.username} (ID: {message.from_user.id})")
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения с контактом для @{message.from_user.username}: {str(e)}")

@router.callback_query(F.data.startswith("select_center_"))
async def process_training_center(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    bot = Bot(token=TOKEN)
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))
        return
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
        center = await conn.fetchrow("SELECT center_name, chat_link FROM training_centers WHERE id = $1", center_id)
        if not center:
            await callback.message.edit_text("УТЦ не найден.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]))
            logger.warning(f"УТЦ ID {center_id} не найден для @{callback.from_user.username}")
            return
    exam_id = await validate_exam_record(fio, personal_number, military_unit, subdivision, specialty, contact)
    if exam_id:
        await update_exam_record(exam_id, None, None)  # Пользователь не добавляет медиа, просто обновляем запись
    else:
        await add_exam_record(fio, subdivision, military_unit, callsign, specialty, contact, personal_number)
    await callback.message.edit_text(
        f"Вы успешно записаны на обучение в {center['center_name']}!\n"
        f"Присоединяйтесь к чату: {center['chat_link']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Перейти в чат", url=center['chat_link'])],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ])
    )
    logger.info(f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) записан на обучение в {center['center_name']}")
    await state.clear()
    await callback.answer()
    await bot.session.close()