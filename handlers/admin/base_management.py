from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_base_management_menu
from utils.excel_utils import import_serials, export_serials
import logging

logger = logging.getLogger(__name__)

router = Router()

class BaseManagement(StatesGroup):
    import_serials = State()

@router.callback_query(F.data == "manage_base")
async def manage_base(callback: CallbackQuery):
    await callback.message.delete()  # Удаляем сообщение
    await callback.message.answer("Управление базой:", reply_markup=get_base_management_menu())
    logger.info(f"Пользователь @{callback.from_user.username} открыл управление базой")

@router.message(StateFilter(BaseManagement.import_serials), F.document)
async def process_import(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    if message.document.mime_type != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        await message.answer("Отправьте Excel-файл.", reply_markup=keyboard)
        logger.error(f"Неверный формат файла от @{message.from_user.username}")
        return
    # Отправляем уведомление о начале импорта
    status_message = await message.answer("Импорт начат, пожалуйста, подождите...")
    file = await message.bot.get_file(message.document.file_id)
    file_io = await message.bot.download_file(file.file_path)
    result, error, invalid_file = await import_serials(file_io, db_pool)
    await status_message.delete()  # Удаляем статусное сообщение
    if error:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        await message.answer(error, reply_markup=keyboard)
        logger.error(f"Ошибка импорта от @{message.from_user.username}: {error}")
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        response = (f"Добавлено: {result['added']}\n"
                    f"Пропущено: {result['skipped']}\n"
                    f"Непринятые номера: {len(result['invalid'])}")
        await message.answer(response, reply_markup=keyboard)
        if invalid_file:
            await message.answer_document(
                document=BufferedInputFile(invalid_file.getvalue(), filename="invalid_serials.xlsx"),
                caption="Файл с невалидными серийными номерами",
                reply_markup=keyboard
            )
        logger.info(f"Импорт завершён пользователем @{message.from_user.username}: {response}")
    await state.clear()

@router.callback_query(F.data == "import_serials")
async def import_serials_prompt(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.delete()  # Удаляем сообщение
    await callback.message.answer("Отправьте Excel-файл с серийными номерами (столбец 'Serial'):", reply_markup=keyboard)
    await state.set_state(BaseManagement.import_serials)
    logger.debug(f"Запрос импорта серийников от @{callback.from_user.username}")

@router.callback_query(F.data == "export_serials")
async def export_serials_handler(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.delete()
        await callback.message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    output = await export_serials(db_pool)
    if output is None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        await callback.message.delete()
        await callback.message.answer("Нет данных для экспорта.", reply_markup=keyboard)
        logger.warning(f"Нет данных для экспорта, запрос от @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.answer_document(
        document=BufferedInputFile(output.getvalue(), filename="serials_export.xlsx"),
        reply_markup=keyboard
    )
    await callback.message.delete()  # Удаляем исходное сообщение
    logger.info(f"Экспорт серийников выполнен пользователем @{callback.from_user.username}")