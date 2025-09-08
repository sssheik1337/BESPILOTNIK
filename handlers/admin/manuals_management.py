from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from keyboards.inline import get_manuals_admin_menu
from database.db import set_manual_file
import logging

router = Router()
logger = logging.getLogger(__name__)

class ManualUpload(StatesGroup):
    waiting_for_file = State()

@router.callback_query(F.data == "manage_manuals")
async def manage_manuals(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Выберите руководство для загрузки:", reply_markup=get_manuals_admin_menu())
    await callback.answer()

@router.callback_query(F.data.startswith("upload_manual_"))
async def prompt_manual_upload(callback: CallbackQuery, state: FSMContext):
    category = callback.data.replace("upload_manual_", "")
    await state.update_data(category=category)
    await callback.message.edit_text(
        "Отправьте файл руководства:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]
        ])
    )
    await state.set_state(ManualUpload.waiting_for_file)
    await callback.answer()

@router.message(ManualUpload.waiting_for_file, F.document)
async def receive_manual_file(message: Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")
    file_id = message.document.file_id
    await set_manual_file(category, file_id)
    await message.answer(
        "Файл сохранён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]
        ])
    )
    await state.clear()

@router.message(ManualUpload.waiting_for_file)
async def invalid_manual_file(message: Message):
    await message.answer(
        "Пожалуйста, отправьте файл.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]
        ])
    )
