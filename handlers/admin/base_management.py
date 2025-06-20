from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from keyboards.inline import get_base_management_menu
from utils.excel_utils import import_serials, export_serials
import logging

logger = logging.getLogger(__name__)

router = Router()

@router.callback_query(F.data == "manage_base")
async def manage_base(callback: CallbackQuery):
    await callback.message.edit_text("Управление базой:", reply_markup=get_base_management_menu())
    logger.info(f"Пользователь @{callback.from_user.username} открыл управление базой")

@router.message(F.document)
async def process_import(message: Message, **data):
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
    file = await message.bot.get_file(message.document.file_id)
    file_io = await message.bot.download_file(file.file_path)
    result, error = await import_serials(file_io, db_pool)
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
                    f"Непринятые номера: {', '.join(result['invalid']) if result['invalid'] else 'Нет'}")
        await message.answer(response, reply_markup=keyboard)
        logger.info(f"Импорт завершён пользователем @{message.from_user.username}: {response}")

@router.callback_query(F.data == "import_serials")
async def import_serials_prompt(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.edit_text("Отправьте Excel-файл с серийными номерами (столбец 'Serial'):", reply_markup=keyboard)
    logger.debug(f"Запрос импорта серийников от @{callback.from_user.username}")

@router.callback_query(F.data == "export_serials")
async def export_serials_handler(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    output = await export_serials(db_pool)
    if output is None:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        await callback.message.edit_text("Нет данных для экспорта.", reply_markup=keyboard)
        logger.warning(f"Нет данных для экспорта, запрос от @{callback.from_user.username}")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.answer_document(
        document=BufferedInputFile(output.getvalue(), filename="serials_export.xlsx"),
        reply_markup=keyboard
    )
    logger.info(f"Экспорт серийников выполнен пользователем @{callback.from_user.username}")