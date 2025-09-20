from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
import re
from pathlib import Path

from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest

from keyboards.inline import get_manuals_admin_menu
from database.db import get_manual_file, set_manual_file
from config import (
    TOKEN,
    LOCAL_BOT_API_CACHE_DIR,
    MANUALS_STORAGE_DIR,
)
from handlers.admin.admin_panel import download_from_local_api, _cleanup_source_file
import logging

router = Router()
logger = logging.getLogger(__name__)


class ManualUpload(StatesGroup):
    waiting_for_file = State()


def _sanitize_manual_filename(category: str, original: str) -> str:
    base_name, *ext_parts = original.rsplit(".", 1)
    extension = f".{ext_parts[0]}" if ext_parts else ""
    candidates = [base_name, category]
    cleaned_parts = []
    for part in candidates:
        if not part:
            continue
        normalized = re.sub(r"[\s]+", "_", part.strip())
        normalized = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_\-]", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        if normalized:
            cleaned_parts.append(normalized)
    if not cleaned_parts:
        cleaned_parts.append("manual")
    filename = "_".join(cleaned_parts)
    return f"{filename}{extension or '.dat'}"


@router.callback_query(F.data == "manage_manuals")
async def manage_manuals(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.message.answer(
        "Выберите руководство для загрузки:", reply_markup=get_manuals_admin_menu()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("upload_manual_"))
async def prompt_manual_upload(callback: CallbackQuery, state: FSMContext):
    category = callback.data.replace("upload_manual_", "")
    await state.update_data(category=category)
    manuals_dir = Path(MANUALS_STORAGE_DIR)
    manuals_dir.mkdir(parents=True, exist_ok=True)
    current_entry = await get_manual_file(category)
    current_file_name = (
        current_entry.get("file_name") if current_entry else None
    )
    reply_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]
        ]
    )

    prompt_lines = ["Отправьте файл руководства."]
    current_path = None
    if current_file_name:
        prompt_lines.append(f"Текущая версия: {current_file_name}")
        candidate = manuals_dir / current_file_name
        if candidate.exists():
            current_path = candidate
    else:
        prompt_lines.append("Текущая версия отсутствует.")

    prompt_text = "\n".join(prompt_lines)

    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    if current_path is not None:
        try:
            await callback.message.answer_document(
                FSInputFile(current_path),
                caption=f"{prompt_text}\n\nТекущая версия руководства во вложении.",
                reply_markup=reply_markup,
            )
        except Exception as exc:  # pragma: no cover - защитное логирование
            logger.warning(
                "Не удалось отправить текущее руководство %s: %s",
                current_file_name,
                exc,
            )
            await callback.message.answer(prompt_text, reply_markup=reply_markup)
    else:
        await callback.message.answer(prompt_text, reply_markup=reply_markup)

    await state.set_state(ManualUpload.waiting_for_file)
    await callback.answer()


@router.message(ManualUpload.waiting_for_file, F.document)
async def receive_manual_file(message: Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")
    if not category:
        await message.answer(
            "Неизвестная категория руководства. Повторите попытку.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]
                ]
            ),
        )
        await state.clear()
        return

    manuals_dir = Path(MANUALS_STORAGE_DIR)
    manuals_dir.mkdir(parents=True, exist_ok=True)

    download_result = None
    try:
        download_result = await download_from_local_api(
            file_id=message.document.file_id,
            token=TOKEN,
            base_dir=str(Path(LOCAL_BOT_API_CACHE_DIR) / "manuals"),
        )

        source_path = Path(download_result.local_path)
        original_name = message.document.file_name or f"{category}.dat"
        sanitized_name = _sanitize_manual_filename(category, original_name)
        target_path = manuals_dir / sanitized_name

        if target_path.exists():
            target_path.unlink()

        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(target_path)

        previous_file = await set_manual_file(category, target_path.name)
        if previous_file and previous_file != target_path.name:
            old_path = manuals_dir / previous_file
            old_path.unlink(missing_ok=True)

        await message.answer(
            "Файл сохранён.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]
                ]
            ),
        )
        await state.clear()
    except Exception as exc:
        logger.error("Не удалось сохранить руководство %s: %s", category, exc)
        await message.answer(
            "Не удалось сохранить файл. Проверьте настройки и попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]
                ]
            ),
        )
        await state.clear()
    finally:
        if download_result:
            await _cleanup_source_file(download_result.source_path)


@router.message(ManualUpload.waiting_for_file)
async def invalid_manual_file(message: Message):
    await message.answer(
        "Пожалуйста, отправьте файл.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]
            ]
        ),
    )
