from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from pathlib import Path

from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest

from keyboards.inline import (
    ManualCategoryCallback,
    ManualFileCallback,
    get_manual_file_actions,
    get_manual_files_menu,
    get_manuals_admin_menu,
    get_manual_delete_all_confirm,
    get_manual_delete_confirm,
    get_manual_post_upload_actions,
    manual_category_cb,
    manual_file_cb,
)
from database.db import (
    add_manual_file,
    delete_all_manual_files,
    delete_manual_file,
    get_manual_file_by_id,
    get_manual_files,
)
from config import (
    TOKEN,
    LOCAL_BOT_API_CACHE_DIR,
    MANUALS_STORAGE_DIR,
    PUBLIC_MEDIA_ROOT,
)
from handlers.admin.admin_panel import download_from_local_api, _cleanup_source_file
from utils.video import compress_video
import logging

router = Router()
logger = logging.getLogger(__name__)

MANUAL_CATEGORIES = {
    "remote_settings": "Настройка пульта",
    "erls_firmware": "Прошивка ЕРЛС",
    "ncu_setup": "Настройка НСУ",
    "drone_guide": "Руководство по дрону",
}


class ManualUpload(StatesGroup):
    waiting_for_file = State()


@router.callback_query(F.data == "manage_manuals")
async def manage_manuals(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.message.answer(
        "Выберите категорию руководства:", reply_markup=get_manuals_admin_menu()
    )
    await callback.answer()


def _category_dir(category: str) -> Path:
    return Path(MANUALS_STORAGE_DIR) / category


def _absolute_path(file_path: str) -> Path:
    candidate = Path(file_path)
    if candidate.is_absolute():
        return candidate
    return Path(PUBLIC_MEDIA_ROOT) / candidate


def _category_title(category: str) -> str:
    return MANUAL_CATEGORIES.get(category, category)


async def _send_category_overview(message_obj, category: str, *, is_admin: bool):
    files = await get_manual_files(category)
    lines = [f"Текущие файлы руководства: {_category_title(category)}"]
    if not files:
        lines.append("Файлы отсутствуют.")
    text = "\n".join(lines)
    reply_markup = get_manual_files_menu(category, files, is_admin=is_admin)
    await message_obj.answer(text, reply_markup=reply_markup)


@router.callback_query(
    manual_category_cb.filter((F.role == "admin") & (F.action == "open"))
)
async def open_manual_category(callback: CallbackQuery, callback_data: dict, state: FSMContext):
    await state.clear()
    callback_data = ManualCategoryCallback.model_validate(callback_data)
    category = callback_data.category
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await state.update_data(category=category)
    await _send_category_overview(callback.message, category, is_admin=True)
    await callback.answer()


async def _prompt_file_upload(callback: CallbackQuery, category: str, state: FSMContext):
    files = await get_manual_files(category)
    if len(files) >= 10:
        await callback.answer("Достигнут лимит: максимум 10 файлов", show_alert=True)
        return False
    await state.update_data(category=category)
    await state.set_state(ManualUpload.waiting_for_file)
    await callback.message.answer(
        f"Категория: {_category_title(category)}. Отправьте документ, фото или видео.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data=manual_category_cb(
                            role="admin", action="open", category=category
                        ).pack(),
                    )
                ]
            ]
        ),
    )
    return True


@router.callback_query(
    manual_category_cb.filter(
        (F.role == "admin") & (F.action.in_({"add", "add_more"}))
    )
)
async def prompt_manual_add(callback: CallbackQuery, callback_data: dict, state: FSMContext):
    callback_data = ManualCategoryCallback.model_validate(callback_data)
    category = callback_data.category
    started = await _prompt_file_upload(callback, category, state)
    if started:
        await callback.answer()



@router.message(ManualUpload.waiting_for_file, F.document | F.photo | F.video)
async def receive_manual_file(message: Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")
    if not category:
        await message.answer(
            "Неизвестная категория руководства. Повторите попытку.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]]
            ),
        )
        await state.clear()
        return

    files = await get_manual_files(category)
    if len(files) >= 10:
        await message.answer(
            "Достигнут лимит: максимум 10 файлов в категории.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data=manual_category_cb(
                                role="admin", action="open", category=category
                            ).pack(),
                        )
                    ]
                ]
            ),
        )
        await state.clear()
        return

    download_result = None
    progress_message = None
    media_kind = None

    try:
        file_id = None
        original_name = None
        if message.document:
            media_kind = "document"
            file_id = message.document.file_id
            original_name = message.document.file_name or "document.bin"
        elif message.photo:
            media_kind = "photo"
            largest_photo = message.photo[-1]
            file_id = largest_photo.file_id
            original_name = f"photo_{file_id}.jpg"
        elif message.video:
            media_kind = "video"
            file_id = message.video.file_id
            original_name = message.video.file_name or f"video_{file_id}.mp4"

        if not file_id or not original_name:
            await message.answer(
                "Пожалуйста, отправьте документ, фото или видео.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад",
                                callback_data=manual_category_cb(
                                    role="admin", action="open", category=category
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )
            return

        download_result = await download_from_local_api(
            file_id=file_id,
            token=TOKEN,
            base_dir=str(Path(LOCAL_BOT_API_CACHE_DIR) / "manuals"),
        )

        source_path = Path(download_result.local_path)
        processed_path = source_path

        if media_kind == "video" and source_path.stat().st_size > 75 * 1024 * 1024:
            progress_message = await message.answer(
                "Видео получено. Выполняется сжатие, это может занять несколько минут..."
            )
            try:
                compressed_path = await compress_video(source_path)
                processed_path = Path(compressed_path)
                if progress_message:
                    try:
                        if processed_path == source_path:
                            await progress_message.edit_text(
                                "Сжатие не потребовалось, используем исходный файл."
                            )
                        else:
                            await progress_message.edit_text("Сжатие завершено ✅")
                    except TelegramBadRequest:
                        pass
            except Exception as exc:
                logger.error("Не удалось сжать видео руководства %s: %s", category, exc)
                if progress_message:
                    try:
                        await progress_message.edit_text(
                            "Не удалось сжать видео, используем исходный файл."
                        )
                    except TelegramBadRequest:
                        pass
                processed_path = source_path

        target_dir = _category_dir(category)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(original_name).name
        target_path = target_dir / safe_name

        if target_path.exists():
            await message.answer(
                "Файл с таким именем уже загружен. Переименуйте файл и отправьте снова.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад",
                                callback_data=manual_category_cb(
                                    role="admin", action="open", category=category
                                ).pack(),
                            )
                        ]
                    ]
                ),
            )
            await state.clear()
            return

        processed_path.replace(target_path)

        if media_kind == "video" and source_path.exists():
            await _cleanup_source_file(source_path)

        relative_path = Path("manuals") / category / safe_name
        await add_manual_file(category, safe_name, str(relative_path))

        await message.answer(
            "Файл добавлен. Что дальше?",
            reply_markup=get_manual_post_upload_actions(category),
        )
        await state.clear()
    except Exception as exc:
        logger.error("Не удалось сохранить руководство %s: %s", category, exc)
        await message.answer(
            "Не удалось сохранить файл. Проверьте настройки и попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data=manual_category_cb(
                                role="admin", action="open", category=category
                            ).pack(),
                        )
                    ]
                ]
            ),
        )
        await state.clear()
    finally:
        if download_result:
            await _cleanup_source_file(download_result.source_path)
        if progress_message:
            try:
                await progress_message.delete()
            except TelegramBadRequest:
                pass


@router.message(ManualUpload.waiting_for_file)
async def invalid_manual_file(message: Message):
    await message.answer(
        "Пожалуйста, отправьте документ, фото или видео.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_manuals")]]
        ),
    )


@router.callback_query(manual_file_cb.filter(F.action == "open"))
async def show_manual_file(callback: CallbackQuery, callback_data: dict):
    callback_data = ManualFileCallback.model_validate(callback_data)
    category = callback_data.category
    file_id = int(callback_data.file_id)
    record = await get_manual_file_by_id(file_id)
    if not record or record["category"] != category:
        await callback.answer("Файл не найден", show_alert=True)
        return

    file_path = _absolute_path(record["file_path"])
    keyboard = get_manual_file_actions(category, file_id, is_admin=True)

    try:
        await callback.message.answer_document(
            FSInputFile(file_path),
            caption=f"{_category_title(category)} — {record['file_name']}",
            reply_markup=keyboard,
        )
    except Exception as exc:
        logger.error("Не удалось отправить файл руководства %s: %s", record["file_name"], exc)
        await callback.message.answer("Не удалось отправить файл.", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(manual_file_cb.filter(F.action == "open_user"))
async def show_manual_file_user(callback: CallbackQuery, callback_data: dict):
    callback_data = ManualFileCallback.model_validate(callback_data)
    category = callback_data.category
    file_id = int(callback_data.file_id)
    record = await get_manual_file_by_id(file_id)
    if not record or record["category"] != category:
        await callback.answer("Файл не найден", show_alert=True)
        return

    file_path = _absolute_path(record["file_path"])
    keyboard = get_manual_file_actions(category, file_id, is_admin=False)
    try:
        await callback.message.answer_document(
            FSInputFile(file_path),
            caption=record["file_name"],
            reply_markup=keyboard,
        )
    except Exception as exc:
        logger.error("Не удалось отправить файл руководства %s: %s", record["file_name"], exc)
        await callback.message.answer("Не удалось отправить файл.", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(manual_file_cb.filter(F.action == "delete_prompt"))
async def confirm_delete_file(callback: CallbackQuery, callback_data: dict):
    callback_data = ManualFileCallback.model_validate(callback_data)
    category = callback_data.category
    file_id = int(callback_data.file_id)
    await callback.message.answer(
        "Удалить выбранный файл?",
        reply_markup=get_manual_delete_confirm(category, file_id),
    )
    await callback.answer()


@router.callback_query(manual_file_cb.filter(F.action == "delete"))
async def delete_file(callback: CallbackQuery, callback_data: dict):
    callback_data = ManualFileCallback.model_validate(callback_data)
    category = callback_data.category
    file_id = int(callback_data.file_id)
    record = await get_manual_file_by_id(file_id)
    if record:
        file_path = _absolute_path(record["file_path"])
        file_path.unlink(missing_ok=True)
    await delete_manual_file(file_id)
    await callback.message.answer("Файл удалён.")
    await _send_category_overview(callback.message, category, is_admin=True)
    await callback.answer()


@router.callback_query(
    manual_category_cb.filter((F.role == "admin") & (F.action == "delete_all"))
)
async def confirm_delete_all(callback: CallbackQuery, callback_data: dict):
    callback_data = ManualCategoryCallback.model_validate(callback_data)
    category = callback_data.category
    await callback.message.answer(
        "Удалить все файлы категории?",
        reply_markup=get_manual_delete_all_confirm(category),
    )
    await callback.answer()


@router.callback_query(
    manual_category_cb.filter(
        (F.role == "admin") & (F.action == "delete_all_confirm")
    )
)
async def delete_all_files(callback: CallbackQuery, callback_data: dict):
    callback_data = ManualCategoryCallback.model_validate(callback_data)
    category = callback_data.category
    files = await get_manual_files(category)
    for record in files:
        file_path = _absolute_path(record["file_path"])
        file_path.unlink(missing_ok=True)
    await delete_all_manual_files(category)
    await callback.message.answer("Все файлы удалены.")
    await _send_category_overview(callback.message, category, is_admin=True)
    await callback.answer()
