from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import get_base_management_menu
from utils.excel_utils import import_serials, export_serials
from database.db import get_defect_reports
from config import MAIN_ADMIN_IDS
import logging
from aiogram.exceptions import TelegramBadRequest
from io import BytesIO
import pandas as pd

logger = logging.getLogger(__name__)

router = Router()

class BaseManagement(StatesGroup):
    import_serials = State()
    report_serial_from = State()
    report_serial_to = State()

@router.callback_query(F.data == "manage_base")
async def manage_base(callback: CallbackQuery):
    await callback.message.delete()
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
    status_message = await message.answer("Импорт начат, пожалуйста, подождите...")
    file = await message.bot.get_file(message.document.file_id)
    file_io = await message.bot.download_file(file.file_path)
    result, error, invalid_file = await import_serials(file_io, db_pool)
    await status_message.delete()
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
    await callback.message.delete()
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
    await callback.message.delete()
    logger.info(f"Экспорт серийников выполнен пользователем @{callback.from_user.username}")

@router.callback_query(F.data == "export_defect_reports")
async def export_defect_reports_prompt(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
    ])
    await callback.message.delete()
    await callback.message.answer("Введите диапазон серийных номеров (от <from> до <to>) или конкретный серийный номер:", reply_markup=keyboard)
    await state.set_state(BaseManagement.report_serial_from)
    logger.debug(f"Запрос выгрузки отчётов от @{callback.from_user.username}")

@router.message(StateFilter(BaseManagement.report_serial_from))
async def process_report_serial(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer("Ошибка сервера. Попробуйте позже.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]))
        return
    text = message.text.strip()
    serial = None
    serial_from = None
    serial_to = None
    if ' ' in text:
        parts = text.split()
        if len(parts) == 3 and parts[1] == 'до':
            serial_from = parts[0]
            serial_to = parts[2]
        else:
            serial = text
    else:
        serial = text
    reports = await get_defect_reports(serial, serial_from, serial_to)
    if not reports:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ])
        await message.answer("Нет отчётов для указанного диапазона/номера.", reply_markup=keyboard)
        logger.warning(f"Нет отчётов для диапазона {serial_from}-{serial_to} или номера {serial}, запрос от @{message.from_user.username}")
        await state.clear()
        return
    data = []
    for report in reports:
        media_links = json.loads(report['media_links'] or "[]")
        photo_links = [media['file_id'] for media in media_links if media['type'] == "photo"]
        video_links = [media['file_id'] for media in media_links if media['type'] in ["video", "video_note"]]
        data.append({
            'Серийный номер': report['serial'],
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
    await state.clear()