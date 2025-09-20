import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from aiogram import Router, F, Bot
from typing import List, Optional
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from keyboards.inline import (
    get_admin_panel_menu,
    get_remove_channel_menu,
    get_edit_channel_menu,
    get_employee_list_menu,
    get_my_appeals_menu,
    get_exam_menu,
    get_training_centers_menu,
)
from database.db import (
    add_admin,
    add_notification_channel,
    get_notification_channels,
    get_admins,
    get_assigned_appeals,
    get_defect_reports,
    add_exam_record,
    update_exam_record,
    get_exam_records,
    add_defect_report,
    set_code_word,
    get_training_centers,
    update_training_center,
    add_training_center,
    get_exam_records_by_personal_number,
)
from config import (
    MAIN_ADMIN_IDS,
    TOKEN,
    API_BASE_URL,
    API_FILE_BASE_URL,
    LOCAL_BOT_API_DATA_DIR,
    LOCAL_BOT_API_REMOTE_DIR,
    LOCAL_BOT_API_CACHE_DIR,
    EXAM_VIDEOS_DIR,
    EXAM_PHOTOS_DIR,
)
from datetime import datetime
import logging
from aiogram.exceptions import TelegramBadRequest
from io import BytesIO
import pandas as pd
import json
from utils.validators import validate_media
from utils.statuses import APPEAL_STATUSES
from utils.video import compress_video
import aiohttp
from aiohttp import ClientError
import shutil
from pathlib import PurePosixPath
import re

logger = logging.getLogger(__name__)

router = Router()


class LocalBotAPIConfigurationError(RuntimeError):
    """Возникает, когда локальный Bot API запущен в режиме --local без корректного каталога данных."""


@dataclass
class DownloadResult:
    local_path: str
    source_path: Optional[Path] = None



class AdminResponse(StatesGroup):
    add_channel = State()
    edit_channel = State()
    add_employee = State()
    defect_report_serial = State()
    defect_report_location = State()
    defect_report_media = State()
    defect_status_serial = State()
    exam_fio = State()
    exam_personal_number = State()
    exam_military_unit = State()
    exam_subdivision = State()
    exam_callsign = State()
    exam_specialty = State()
    exam_contact = State()
    exam_training_center = State()
    exam_video = State()
    exam_photo = State()
    report_serial_from = State()
    report_serial_to = State()
    change_code_word = State()
    add_training_center_name = State()
    add_training_center_link = State()
    edit_training_center_link = State()


COLON_VARIANTS = (":", "\uf03a", "\uff1a", "\ufe55", "\ufe13", "\u2236")


def _replace_colon_variants(value: str, replacement: str) -> str:
    for variant in COLON_VARIANTS:
        value = value.replace(variant, replacement)
    return value


def _sanitize_component_for_storage(component: str) -> str:
    sanitized = _replace_colon_variants(component, "_")
    return sanitized


def _normalize_component(component: str) -> str:
    normalized = _replace_colon_variants(component, "")
    return normalized.replace("_", "").replace("-", "").lower()


def _safe_log_arg(arg):
    if isinstance(arg, (Path, PurePosixPath)):
        arg = str(arg)
    if isinstance(arg, str):
        return arg.encode("ascii", errors="backslashreplace").decode("ascii")

    try:
        return str(arg)
    except Exception:
        return repr(arg)


def _safe_log_args(*args):
    return tuple(_safe_log_arg(arg) for arg in args)


def _sanitize_filename_component(value: str) -> str:
    replaced = _replace_colon_variants(value or "", " ")
    cleaned = re.sub(r"[\s]+", "_", replaced.strip())
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_\-]", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "media"


def _exam_media_basename(fio: str, training_center: str) -> str:
    fio_component = _sanitize_filename_component(fio)
    center_component = _sanitize_filename_component(training_center)
    return "_".join(part for part in [fio_component, center_component] if part)


def _ensure_unique_media_path(directory: Path, base_name: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{base_name}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{base_name}_{counter}{suffix}"
        counter += 1
    return candidate


async def _resolve_training_center_name(
    state: FSMContext,
    state_data: dict,
    db_pool,
    training_center_id: int,
) -> str:
    name = state_data.get("training_center_name")
    if name:
        return name
    fetched = None
    if db_pool:
        async with db_pool.acquire() as conn:
            fetched = await conn.fetchval(
                "SELECT center_name FROM training_centers WHERE id = $1",
                training_center_id,
            )
    name = fetched or f"УТЦ_{training_center_id}"
    await state.update_data(training_center_name=name)
    return name


async def _cleanup_source_file(path: Optional[Path]) -> None:
    if not path:
        return

    def _remove(target: Path) -> None:
        try:
            target.unlink()
        except FileNotFoundError:
            return
        except Exception as exc:  # pragma: no cover - диагностика окружения
            logger.warning(
                "Не удалось удалить исходный файл %s: %s",
                *_safe_log_args(target, exc),
            )

    await asyncio.to_thread(_remove, path)


def _candidate_component_names(component: str) -> List[str]:
    variants = {component}

    if any(variant in component for variant in COLON_VARIANTS):
        variants.add(_replace_colon_variants(component, "_"))
        variants.add(_replace_colon_variants(component, "-"))
        variants.add(_replace_colon_variants(component, ""))
        for variant in COLON_VARIANTS:
            if variant in component or ":" in component:
                variants.add(component.replace(":", variant))
                variants.add(_replace_colon_variants(component, variant))
    return list(variants)


def _resolve_local_path(local_data_root: Path, remote_relative: PurePosixPath) -> Optional[Path]:
    try:
        candidate = local_data_root.joinpath(*remote_relative.parts)
        if candidate.exists():
            return candidate
    except (OSError, ValueError):
        pass

    current_paths = [local_data_root]
    for part in remote_relative.parts:
        next_paths = []
        for base in current_paths:
            resolved = None
            for variant in _candidate_component_names(part):
                candidate = base / variant
                if candidate.exists():
                    resolved = candidate
                    break
            if resolved is None:
                normalized_target = _normalize_component(part)
                try:
                    for child in base.iterdir():
                        if _normalize_component(child.name) == normalized_target:
                            resolved = child
                            break
                except OSError:
                    resolved = None
            if resolved is not None:
                next_paths.append(resolved)
        if not next_paths:
            return None
        current_paths = next_paths
    return current_paths[0] if current_paths else None


async def download_from_local_api(file_id: str, token: str, base_dir: str) -> DownloadResult:
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    api_base_url = API_BASE_URL.format(token=token).rstrip("/")
    file_base_url = API_FILE_BASE_URL.format(token=token).rstrip("/")
    remote_data_root = PurePosixPath(LOCAL_BOT_API_REMOTE_DIR.rstrip("/"))
    local_data_root = Path(LOCAL_BOT_API_DATA_DIR) if LOCAL_BOT_API_DATA_DIR else None

    async def _download_via_telegram(
        session: aiohttp.ClientSession,
        preferred_relative: Optional[PurePosixPath],
    ) -> DownloadResult:
        logger.info(
            "Локальный бот API недоступен, загружаем файл %s через публичный API Telegram",
            file_id,
        )
        async with session.get(
            f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id}
        ) as get_file_resp:
            if get_file_resp.status != 200:
                body = await get_file_resp.text()
                raise Exception(
                    f"Ошибка Telegram getFile: HTTP {get_file_resp.status}, ответ: {body}"
                )
            data = await get_file_resp.json()

        telegram_relative = PurePosixPath(data["result"]["file_path"])
        relative = preferred_relative or telegram_relative
        safe_relative = Path(*(_sanitize_component_for_storage(p) for p in relative.parts))
        destination = base_path / safe_relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        async with session.get(
            f"https://api.telegram.org/file/bot{token}/{telegram_relative.as_posix()}"
        ) as file_resp:
            if file_resp.status != 200:
                body = await file_resp.text()
                raise Exception(
                    f"Ошибка загрузки файла Telegram: HTTP {file_resp.status}, ответ: {body}"
                )
            with destination.open("wb") as file_obj:
                async for chunk in file_resp.content.iter_chunked(1 << 14):
                    file_obj.write(chunk)
        logger.debug(
            "Файл %s загружен через Telegram API: %s",
            *_safe_log_args(file_id, destination),
        )
        return DownloadResult(str(destination))

    remote_relative: Optional[PurePosixPath] = None

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{api_base_url}/getMe", ssl=False) as test_resp:
                logger.debug(
                    "Тестовый запрос к %s/getMe, статус: %s",
                    api_base_url,
                    test_resp.status,
                )
                if test_resp.status != 200:
                    raise Exception(f"Сервер недоступен: HTTP {test_resp.status}")

            async with session.get(
                f"{api_base_url}/getFile", params={"file_id": file_id}, ssl=False
            ) as resp:
                logger.debug(
                    "HTTP-запрос getFile: %s/getFile?file_id=%s, статус: %s",
                    api_base_url,
                    file_id,
                    resp.status,
                )
                if resp.status != 200:
                    raise Exception(
                        f"Ошибка getFile: HTTP {resp.status}, ответ: {await resp.text()}"
                    )
                data = await resp.json()
                if not data.get("ok"):
                    raise Exception(f"Ошибка getFile: {data}")
                file_path = data["result"]["file_path"]
                logger.debug("Получен file_path: %s", file_path)

                sanitized_path = file_path
                is_remote_local = file_path.startswith(f"{remote_data_root}/")
                if is_remote_local:
                    sanitized_path = file_path.replace(f"{remote_data_root}/", "", 1)

                remote_relative = PurePosixPath(sanitized_path)
                safe_relative = Path(
                    *(_sanitize_component_for_storage(part) for part in remote_relative.parts)
                )
                local_path = base_path / safe_relative

                if is_remote_local:
                    if not local_data_root:
                        message = (
                            "LOCAL_BOT_API_DATA_DIR не настроен, хотя Bot API работает в режиме --local. "
                            "Укажите путь к примонтированному каталогу данных (file_id=%s)."
                        ) % file_id
                        logger.error(message)
                        raise LocalBotAPIConfigurationError(message)

                    source_path = _resolve_local_path(local_data_root, remote_relative)
                    if not source_path or not source_path.exists():
                        formatted_message = (
                            "Файл %s отсутствует в локальном каталоге Bot API (%s). "
                            "Проверьте параметр LOCAL_BOT_API_DATA_DIR и монтирование тома."
                        ) % (file_id, remote_relative)
                        logger.error(formatted_message)
                        raise LocalBotAPIConfigurationError(formatted_message)

                    if local_path.exists():
                        logger.debug(
                            "Файл %s уже скопирован локально: %s",
                            *_safe_log_args(file_id, local_path),
                        )
                        return DownloadResult(str(local_path))

                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        await asyncio.to_thread(shutil.copy2, source_path, local_path)
                        logger.debug(
                            "Файл %s скопирован из локального каталога %s в %s",
                            *_safe_log_args(file_id, source_path, local_path),
                        )
                        return DownloadResult(str(local_path), source_path)
                    except Exception as copy_exc:
                        logger.warning(
                            "Не удалось скопировать файл %s из %s: %s",
                            *_safe_log_args(file_id, source_path, copy_exc),
                        )

                if local_path.exists():
                    logger.debug(
                        "Файл найден локально: %s", *_safe_log_args(local_path)
                    )
                    return DownloadResult(str(local_path))

                url = f"{file_base_url}/{remote_relative.as_posix()}"
                async with session.get(url, ssl=False) as file_resp:
                    logger.debug("HTTP-запрос к %s, статус: %s", url, file_resp.status)
                    if file_resp.status != 200:
                        raise Exception(
                            f"Ошибка загрузки файла: HTTP {file_resp.status}, ответ: {await file_resp.text()}"
                        )
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    with local_path.open("wb") as f:
                        async for chunk in file_resp.content.iter_chunked(1 << 14):
                            f.write(chunk)
                    logger.debug(
                        "Файл загружен через локальный HTTP и сохранён: %s",
                        *_safe_log_args(local_path),
                    )
                return DownloadResult(str(local_path))
        except LocalBotAPIConfigurationError:
            raise
        except (ClientError, asyncio.TimeoutError) as exc:
            logger.warning(
                "Локальный Telegram Bot API недоступен (%s), выполняем загрузку через публичный API",
                exc,
            )
            return await _download_via_telegram(session, None)
        except Exception as exc:
            logger.warning(
                "Ошибка при загрузке файла через локальный API: %s. Пробуем публичный API",
                exc,
            )
            return await _download_via_telegram(session, remote_relative)


@router.callback_query(F.data == "admin_panel")
async def admin_panel_prompt(callback: CallbackQuery, **data):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        await callback.message.edit_text(
            "Доступ запрещён.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(
            f"Попытка доступа к админ-панели от неадминистратора @{callback.from_user.username}"
        )
        return
    await callback.message.edit_text(
        "Панель администратора:", reply_markup=get_admin_panel_menu()
    )
    logger.debug(
        f"Администратор @{callback.from_user.username} (ID: {callback.from_user.id}) открыл панель администратора"
    )


@router.callback_query(F.data.startswith("select_exam_"))
async def select_exam_record(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        return
    exam_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        record = await conn.fetchrow(
            """
            SELECT er.*, tc.center_name
            FROM exam_records er
            LEFT JOIN training_centers tc ON er.training_center_id = tc.id
            WHERE er.exam_id = $1
            """,
            exam_id,
        )
        if not record:
            await callback.message.edit_text(
                "Запись не найдена.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="exam_menu"
                            )
                        ]
                    ]
                ),
            )
            logger.warning(
                f"Запись экзамена ID {exam_id} не найдена для @{callback.from_user.username}"
            )
            return
    await state.update_data(
        exam_id=exam_id,
        fio=record["fio"],
        personal_number=record["personal_number"],
        military_unit=record["military_unit"],
        subdivision=record["subdivision"],
        callsign=record["callsign"],
        specialty=record["specialty"],
        contact=record["contact"],
        training_center_id=record["training_center_id"],
        training_center_name=record.get("center_name")
        or f"УТЦ_{record['training_center_id']}",
    )
    await callback.message.edit_text(
        "Прикрепите видео:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_video)
    logger.debug(
        f"Выбрана запись экзамена ID {exam_id} для @{callback.from_user.username}"
    )


@router.callback_query(F.data == "new_exam_record")
async def new_exam_record(callback: CallbackQuery, state: FSMContext):
    await state.update_data(exam_id=None)  # Очищаем exam_id для новой записи
    await callback.message.edit_text(
        "Введите военную часть (например, В/Ч 29657):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_military_unit)
    logger.debug(
        f"Администратор @{(callback.from_user.username or 'неизвестно')} выбрал создание новой записи экзамена"
    )


@router.callback_query(F.data == "exam_menu")
async def exam_menu_prompt(callback: CallbackQuery, **data):
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
        return
    await callback.message.edit_text("Меню экзаменов:", reply_markup=get_exam_menu())
    logger.debug(
        f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) запросил меню экзаменов"
    )


@router.callback_query(F.data == "take_exam")
async def take_exam_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "⚠️ Внимание!\n"
        "Продолжая использовать бот, вы автоматически соглашаетесь с обработкой ваших персональных данных.\n"
        "Введите ФИО:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_fio)
    logger.debug(
        f"Пользователь @{callback.from_user.username} (ID: {callback.from_user.id}) начал процесс принятия экзамена"
    )


@router.message(StateFilter(AdminResponse.exam_fio))
async def process_exam_fio(message: Message, state: FSMContext):
    fio = message.text.strip()
    await state.update_data(fio=fio)
    await message.answer(
        "Введите личный номер или жетон (например, АВ-449852):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_personal_number)
    logger.debug(
        f"ФИО {fio} принято от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.message(StateFilter(AdminResponse.exam_personal_number))
async def process_personal_number(
    message: Message, state: FSMContext, bot: Bot, **data
):
    personal_number = message.text.strip()
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        return
    await state.update_data(personal_number=personal_number)
    logger.debug(
        f"Личный номер {personal_number} сохранён в состоянии для @{message.from_user.username} (ID: {message.from_user.id})"
    )
    async with db_pool.acquire() as conn:
        records = await get_exam_records_by_personal_number(personal_number)
        if records:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"Запись №{r['exam_id']}: {r['fio']}",
                            callback_data=f"select_exam_{r['exam_id']}",
                        )
                    ]
                    for r in records
                ]
            )
            keyboard.inline_keyboard.append(
                [
                    InlineKeyboardButton(
                        text="Создать новую запись", callback_data="new_exam_record"
                    )
                ]
            )
            keyboard.inline_keyboard.append(
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            )
            await message.answer(
                "Найдены существующие записи. Выберите запись или создайте новую:",
                reply_markup=keyboard,
            )
            logger.debug(
                f"Найдено {len(records)} записей для личного номера {personal_number} от @{message.from_user.username}"
            )
        else:
            await message.answer(
                "Введите военную часть (например, В/Ч 29657):",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="exam_menu"
                            )
                        ]
                    ]
                ),
            )
            await state.set_state(AdminResponse.exam_military_unit)
            logger.debug(
                f"Записей для личного номера {personal_number} не найдено, продолжаем ввод данных для @{message.from_user.username}"
            )
    try:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        logger.debug(
            f"Сообщение с личным номером удалено для @{message.from_user.username}"
        )
    except TelegramBadRequest as e:
        logger.error(
            f"Ошибка удаления сообщения с личным номером для @{message.from_user.username}: {str(e)}"
        )


@router.message(StateFilter(AdminResponse.exam_military_unit))
async def process_exam_military_unit(message: Message, state: FSMContext):
    military_unit = message.text.strip()
    await state.update_data(military_unit=military_unit)
    await message.answer(
        "Введите подразделение:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_subdivision)
    logger.debug(
        f"В/Ч {military_unit} принято от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.message(StateFilter(AdminResponse.exam_subdivision))
async def process_exam_subdivision(message: Message, state: FSMContext):
    subdivision = message.text.strip()
    await state.update_data(subdivision=subdivision)
    await message.answer(
        "Введите позывной:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_callsign)
    logger.debug(
        f"Подразделение {subdivision} принято от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.message(StateFilter(AdminResponse.exam_callsign))
async def process_exam_callsign(message: Message, state: FSMContext):
    callsign = message.text.strip()
    await state.update_data(callsign=callsign)
    await message.answer(
        "Введите направление:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_specialty)
    logger.debug(
        f"Позывной {callsign} принят от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.message(StateFilter(AdminResponse.exam_specialty))
async def process_exam_specialty(message: Message, state: FSMContext):
    specialty = message.text.strip()
    await state.update_data(specialty=specialty)
    await message.answer(
        "Введите контакт для связи в Telegram:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_contact)


@router.message(StateFilter(AdminResponse.exam_contact))
async def process_exam_contact(message: Message, state: FSMContext, **data):
    contact = message.text.strip()
    await state.update_data(contact=contact)
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        return
    async with db_pool.acquire() as conn:
        centers = await conn.fetch(
            "SELECT id, center_name FROM training_centers WHERE center_name IS NOT NULL ORDER BY center_name"
        )
        if not centers:
            logger.error("Учебные центры с валидными названиями не найдены")
            await message.answer(
                "Ошибка: Нет доступных учебных центров. Обратитесь к администратору.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="exam_menu"
                            )
                        ]
                    ]
                ),
            )
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
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
        )
        await message.answer("Выберите учебный центр:", reply_markup=keyboard)
    await state.set_state(AdminResponse.exam_training_center)
    logger.debug(
        f"Контакт {contact} принят от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.message(StateFilter(AdminResponse.exam_video), F.video)
async def process_exam_video(message: Message, state: FSMContext, bot: Bot, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        await state.clear()
        return

    download_result: Optional[DownloadResult] = None

    try:
        if message.video.file_size > 2_000_000_000:  # Проверка размера (2 ГБ)
            await message.answer(
                "Видео слишком большое (максимум 2 ГБ).",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="exam_menu"
                            )
                        ]
                    ]
                ),
            )
            logger.warning(
                f"Видео слишком большое ({message.video.file_size} байт) от @{message.from_user.username}"
            )
            await state.clear()
            return

        # Проверяем, есть ли training_center_id в состоянии
        state_data = await state.get_data()
        if "training_center_id" not in state_data:
            logger.error(
                f"training_center_id отсутствует в состоянии для @{message.from_user.username}"
            )
            await message.answer(
                "Ошибка: не выбран учебный центр.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="exam_menu"
                            )
                        ]
                    ]
                ),
            )
            await state.clear()
            return

        download_result = await download_from_local_api(
            file_id=message.video.file_id,
            token=TOKEN,
            base_dir=LOCAL_BOT_API_CACHE_DIR,
        )
        local_path = download_result.local_path
        progress_message = await message.answer(
            "Видео получено. Выполняется сжатие, это может занять несколько минут..."
        )
        try:
            compressed_path = await compress_video(local_path)
        except Exception:
            if progress_message:
                try:
                    await progress_message.edit_text(
                        "Не удалось сжать видео, используем исходный файл."
                    )
                except TelegramBadRequest:
                    pass
            raise
        else:
            if progress_message:
                try:
                    if Path(compressed_path) == Path(local_path):
                        await progress_message.edit_text(
                            "Сжатие не потребовалось, используем исходный файл."
                        )
                    else:
                        await progress_message.edit_text("Сжатие завершено ✅")
                except TelegramBadRequest:
                    pass
        fio = state_data.get("fio", "")
        training_center_id = state_data.get("training_center_id")
        training_center_name = await _resolve_training_center_name(
            state,
            state_data,
            db_pool,
            training_center_id,
        ) if training_center_id is not None else _sanitize_filename_component("неизвестно")

        compressed_file = Path(compressed_path)
        suffix = compressed_file.suffix or ".mp4"
        base_name = _exam_media_basename(fio, training_center_name)
        final_path = _ensure_unique_media_path(Path(EXAM_VIDEOS_DIR), base_name, suffix)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        compressed_file.replace(final_path)

        await state.update_data(video_link=final_path.name)
        await message.answer(
            "Видео принято. Загрузите фото (до 5 штук) или завершите.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Завершить", callback_data="finish_exam"
                        )
                    ]
                ]
            ),
        )
        logger.debug(
            f"Видео принято от @{message.from_user.username} (ID: {message.from_user.id}), file_id: {message.video.file_id}, сохранено как {final_path.name}"
        )
        await state.set_state(AdminResponse.exam_photo)
    except LocalBotAPIConfigurationError as config_error:
        logger.error(
            "Ошибка конфигурации локального Bot API при обработке видео от @%s: %s",
            message.from_user.username,
            config_error,
        )
        await message.answer(
            "Локальный Bot API работает в режиме --local, но путь к данным не настроен. "
            "Укажите LOCAL_BOT_API_DATA_DIR и примонтируйте каталог перед повторной загрузкой.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка обработки видео от @{message.from_user.username}: {e}")
        await message.answer(
            f"Ошибка сервера: {str(e)}. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        await state.clear()
    finally:
        if download_result:
            await _cleanup_source_file(download_result.source_path)


@router.message(StateFilter(AdminResponse.exam_photo))
async def process_exam_photo(message: Message, state: FSMContext, **data):
    data_state = await state.get_data()
    photo_links = data_state.get("photo_links", [])
    db_pool = data.get("db_pool")
    if message.photo:
        download_result = None
        try:
            download_result = await download_from_local_api(
                file_id=message.photo[-1].file_id,
                token=TOKEN,
                base_dir=str(Path(LOCAL_BOT_API_CACHE_DIR) / "photos"),
            )
            source_path = Path(download_result.local_path)
            suffix = source_path.suffix or ".jpg"
            fio = data_state.get("fio", "")
            training_center_id = data_state.get("training_center_id")
            training_center_name = await _resolve_training_center_name(
                state,
                data_state,
                db_pool,
                training_center_id,
            ) if training_center_id is not None else _sanitize_filename_component("центр")
            base_name = _exam_media_basename(fio, training_center_name)
            indexed_base = f"{base_name}_{len(photo_links) + 1}"
            final_path = _ensure_unique_media_path(
                Path(EXAM_PHOTOS_DIR), indexed_base, suffix
            )
            final_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.replace(final_path)
            photo_links.append(final_path.name)
            await state.update_data(photo_links=photo_links)
            await message.answer(
                f"Фото добавлено ({len(photo_links)}/10). Прикрепите ещё или нажмите 'Готово':",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Готово", callback_data="finish_exam")]
                    ]
                ),
            )
            logger.debug(
                f"Фото добавлено для экзамена от @{message.from_user.username} (ID: {message.from_user.id}), сохранено как {final_path.name}"
            )
        except Exception as exc:
            logger.error(
                "Ошибка сохранения фото для экзамена от @%s: %s",
                message.from_user.username,
                exc,
            )
            await message.answer(
                "Не удалось сохранить фото. Попробуйте снова или завершите без фото.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Готово", callback_data="finish_exam")]
                    ]
                ),
            )
        finally:
            if download_result:
                await _cleanup_source_file(download_result.source_path)
    else:
        await message.answer(
            "Пожалуйста, прикрепите фото или нажмите 'Готово'.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Готово", callback_data="finish_exam")]
                ]
            ),
        )
        logger.warning(
            f"Некорректный ввод фото для экзамена от @{message.from_user.username}"
        )


@router.callback_query(
    F.data.startswith("select_center_"), StateFilter(AdminResponse.exam_training_center)
)
async def process_training_center(callback: CallbackQuery, state: FSMContext, **data):
    logger.debug(
        f"Обработка select_center_ в admin_panel.py для @{callback.from_user.username} (ID: {callback.from_user.id})"
    )
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
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
        if not is_admin:
            logger.debug(
                f"Пропускаем select_center_ для не-администратора @{username} (ID: {user_id})"
            )
            await callback.answer()
            return  # Пропускаем для не-админов
    if not hasattr(callback, "message") or not callback.message:
        logger.error(f"CallbackQuery без сообщения для @{username} (ID: {user_id})")
        await callback.answer("Ошибка: сообщение не найдено.", show_alert=True)
        return
    training_center_id = int(callback.data.split("_")[-1])
    center_name = None
    async with db_pool.acquire() as conn:
        center_name = await conn.fetchval(
            "SELECT center_name FROM training_centers WHERE id = $1",
            training_center_id,
        )
    await state.update_data(
        training_center_id=training_center_id,
        training_center_name=center_name or f"УТЦ_{training_center_id}",
    )
    await callback.message.edit_text(
        "Прикрепите видео:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        ),
    )
    await state.set_state(AdminResponse.exam_video)
    logger.debug(
        f"Учебный центр ID {training_center_id} выбран пользователем @{username} (ID: {user_id})"
    )
    await callback.answer()


@router.callback_query(F.data == "finish_exam")
async def finish_exam(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        await state.clear()
        return

    try:
        state_data = await state.get_data()
        required_fields = [
            "fio",
            "personal_number",
            "military_unit",
            "subdivision",
            "callsign",
            "specialty",
            "contact",
            "training_center_id",
            "video_link",
        ]
        missing_fields = [field for field in required_fields if field not in state_data]
        if missing_fields:
            logger.error(
                f"Недостаточно данных для сохранения экзамена: {missing_fields}"
            )
            await callback.message.edit_text(
                f"Ошибка: отсутствуют данные ({', '.join(missing_fields)}).",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="exam_menu"
                            )
                        ]
                    ]
                ),
            )
            await state.clear()
            return

        fio = state_data["fio"]
        personal_number = state_data["personal_number"]
        military_unit = state_data["military_unit"]
        subdivision = state_data["subdivision"]
        callsign = state_data["callsign"]
        specialty = state_data["specialty"]
        contact = state_data["contact"]
        training_center_id = state_data["training_center_id"]
        video_link = state_data["video_link"]
        photo_links = state_data.get("photo_links", [])

        existing_exam_id = state_data.get("exam_id")
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")

        if existing_exam_id:
            await update_exam_record(
                exam_id=existing_exam_id,
                video_link=video_link,
                photo_links=photo_links,
                accepted_date=now_str,
            )
            exam_id = existing_exam_id
            result_text = "обновлён"
        else:
            exam_id = await add_exam_record(
                fio=fio,
                subdivision=subdivision,
                military_unit=military_unit,
                callsign=callsign,
                specialty=specialty,
                contact=contact,
                personal_number=personal_number,
                training_center_id=training_center_id,
                video_link=video_link,
                photo_links=photo_links,
                application_date=now_str,
                accepted_date=now_str,
            )
            result_text = "успешно добавлен"

        await callback.message.edit_text(
            f"Экзамен №{exam_id} {result_text}!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        logger.info(
            f"Экзамен №{exam_id} {result_text} пользователем @{callback.from_user.username}"
        )
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка сохранения экзамена: {e}")
        await callback.message.edit_text(
            f"Ошибка сервера: {str(e)}. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        await state.clear()


@router.callback_query(F.data == "change_code_word")
async def change_code_word_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        await callback.message.edit_text(
            "Доступ запрещён.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(
            f"Попытка изменения кодового слова от неадминистратора @{callback.from_user.username}"
        )
        return
    await callback.message.edit_text(
        "Введите новое кодовое слово:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
            ]
        ),
    )
    await state.set_state(AdminResponse.change_code_word)
    logger.debug(
        f"Администратор @{callback.from_user.username} (ID: {callback.from_user.id}) запросил изменение кодового слова"
    )


@router.message(StateFilter(AdminResponse.change_code_word))
async def process_code_word(message: Message, state: FSMContext):
    code_word = message.text.strip()
    await set_code_word(code_word)
    await message.answer(
        "Кодовое слово успешно обновлено!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
            ]
        ),
    )
    logger.info(
        f"Кодовое слово обновлено администратором @{message.from_user.username} (ID: {message.from_user.id})"
    )
    await state.clear()


@router.callback_query(F.data == "manage_training_centers")
async def manage_training_centers_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        await callback.message.edit_text(
            "Доступ запрещён.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(
            f"Попытка управления УТЦ от неадминистратора @{callback.from_user.username}"
        )
        return
    centers = await get_training_centers()
    await callback.message.edit_text(
        "Управление УТЦ:", reply_markup=get_training_centers_menu(centers)
    )
    logger.debug(
        f"Администратор @{callback.from_user.username} (ID: {callback.from_user.id}) запросил управление УТЦ"
    )


@router.callback_query(F.data == "add_training_center")
async def add_training_center_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        await callback.message.edit_text(
            "Доступ запрещён.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            ),
        )
        logger.warning(
            f"Попытка добавления УТЦ от неадминистратора @{callback.from_user.username}"
        )
        return
    await callback.message.edit_text(
        "Введите название УТЦ:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="manage_training_centers"
                    )
                ]
            ]
        ),
    )
    await state.set_state(AdminResponse.add_training_center_name)
    logger.debug(
        f"Администратор @{callback.from_user.username} (ID: {callback.from_user.id}) запросил добавление УТЦ"
    )


@router.message(StateFilter(AdminResponse.add_training_center_name))
async def process_training_center_name(message: Message, state: FSMContext):
    center_name = message.text.strip()
    await state.update_data(center_name=center_name)
    await message.answer(
        "Введите ссылку на чат УТЦ:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="manage_training_centers"
                    )
                ]
            ]
        ),
    )
    await state.set_state(AdminResponse.add_training_center_link)
    logger.debug(
        f"Название УТЦ {center_name} принято от @{message.from_user.username} (ID: {message.from_user.id})"
    )


@router.message(StateFilter(AdminResponse.add_training_center_link))
async def process_training_center_link(message: Message, state: FSMContext):
    chat_link = message.text.strip()
    data_state = await state.get_data()
    center_name = data_state.get("center_name")
    await add_training_center(center_name, chat_link)
    await message.answer(
        f"УТЦ {center_name} успешно добавлен!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="manage_training_centers"
                    )
                ]
            ]
        ),
    )
    logger.info(
        f"УТЦ {center_name} добавлен администратором @{message.from_user.username} (ID: {message.from_user.id})"
    )
    await state.clear()


@router.callback_query(F.data.startswith("edit_center_"))
async def edit_training_center_prompt(callback: CallbackQuery, state: FSMContext):
    center_id = int(callback.data.split("_")[-1])
    await callback.message.edit_text(
        "Введите новую ссылку на чат УТЦ:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="manage_training_centers"
                    )
                ]
            ]
        ),
    )
    await state.set_state(AdminResponse.edit_training_center_link)
    await state.update_data(center_id=center_id)
    logger.debug(
        f"Администратор @{callback.from_user.username} (ID: {callback.from_user.id}) запросил редактирование УТЦ ID {center_id}"
    )


@router.message(StateFilter(AdminResponse.edit_training_center_link))
async def process_edit_training_center_link(message: Message, state: FSMContext):
    chat_link = message.text.strip()
    data_state = await state.get_data()
    center_id = data_state.get("center_id")
    await update_training_center(center_id, chat_link)
    await message.answer(
        "Ссылка на чат УТЦ обновлена!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="manage_training_centers"
                    )
                ]
            ]
        ),
    )
    logger.info(
        f"Ссылка на чат УТЦ ID {center_id} обновлена администратором @{message.from_user.username} (ID: {message.from_user.id})"
    )
    await state.clear()


@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery, **data):
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
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка доступа к статистике от неадминистратора @{callback.from_user.username}"
        )
        return
    async with db_pool.acquire() as conn:
        status_counts = await conn.fetch(
            "SELECT COUNT(*) as total, status FROM appeals GROUP BY status"
        )
        admin_stats = await conn.fetch("SELECT username, appeals_taken FROM admins")
    if not status_counts and not admin_stats:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text(
            "Нет данных по заявкам или сотрудникам.", reply_markup=keyboard
        )
        logger.info(f"Статистика пуста, запрос от @{callback.from_user.username}")
        return
    response = "Статистика заявок:\n"
    for count in status_counts:
        status_display = APPEAL_STATUSES.get(
            count["status"], count["status"]
        )  # Используем словарь для перевода
        response += f"{status_display}: {count['total']}\n"
    response += "\nСтатистика сотрудников:\n"
    for admin in admin_stats:
        response += f"@{admin['username']}: {admin['appeals_taken']} заявок\n"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]
    )
    await callback.message.edit_text(response, reply_markup=keyboard)
    logger.info(f"Статистика запрошена пользователем @{callback.from_user.username}")


@router.callback_query(F.data == "add_employee")
async def add_employee_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка добавления сотрудника от неадминистратора @{callback.from_user.username}"
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ]
    )
    await callback.message.edit_text(
        "Введите Telegram ID и username сотрудника (формат: ID @username). Если username отсутствует, укажите 'Нет'. "
        "Узнать свой Telegram ID можно через @userinfobot, отправив ему команду /start.",
        reply_markup=keyboard,
    )
    await state.set_state(AdminResponse.add_employee)
    logger.debug(f"Запрос добавления сотрудника от @{callback.from_user.username}")


@router.message(StateFilter(AdminResponse.add_employee))
async def process_add_employee(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
                ]
            ),
        )
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
            ]
        )
        await message.answer("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка добавления сотрудника от неадминистратора @{message.from_user.username}"
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ]
    )
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError("Формат: ID @username или ID Нет")
        admin_id = int(parts[0])
        username = parts[1].lstrip("@") if parts[1] != "Нет" else None
        await add_admin(admin_id, username)
        await message.answer(
            f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен.",
            reply_markup=keyboard,
        )
        logger.info(
            f"Сотрудник {'@' + username if username else 'без username'} (ID: {admin_id}) добавлен пользователям @{message.from_user.username}"
        )
        await state.clear()
    except ValueError as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(
            f"Неверный формат ввода сотрудника {message.text} от @{message.from_user.username}"
        )
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(
            f"Ошибка добавления сотрудника: {str(e)} от @{message.from_user.username}"
        )


@router.callback_query(F.data == "add_channel")
async def add_channel_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка добавления канала от неадминистратора @{callback.from_user.username}"
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ]
    )
    await callback.message.edit_text(
        "Введите данные канала/группы (формат: @username [topic_id]):",
        reply_markup=keyboard,
    )
    await state.set_state(AdminResponse.add_channel)
    logger.debug(f"Запрос добавления канала от @{callback.from_user.username}")


@router.message(StateFilter(AdminResponse.add_channel))
async def process_add_channel(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
                ]
            ),
        )
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
            ]
        )
        await message.answer("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка добавления канала от неадминистратора @{message.from_user.username}"
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
        ]
    )
    try:
        parts = message.text.split()
        if len(parts) not in [1, 2]:
            raise ValueError("Формат: @username [topic_id]")
        channel_name = parts[0]
        topic_id = int(parts[1]) if len(parts) == 2 else None
        if not channel_name.startswith("@"):
            raise ValueError("Название канала должно начинаться с @")
        chat = await message.bot.get_chat(channel_name)
        channel_id = chat.id
        admins = await message.bot.get_chat_administrators(channel_id)
        bot_id = (await message.bot.get_me()).id
        if not any(admin.user.id == bot_id for admin in admins):
            await message.answer(
                "Бот должен быть администратором в группе/канале.",
                reply_markup=keyboard,
            )
            logger.error(
                f"Бот не является администратором в канале {channel_name} при добавлении от @{message.from_user.username}"
            )
            return
        try:
            await message.bot.send_message(
                chat_id=channel_id,
                message_thread_id=topic_id,
                text="Тестовое сообщение",
            )
        except TelegramBadRequest:
            await message.answer(
                "Канал/группа недоступна или topic_id неверный.", reply_markup=keyboard
            )
            logger.error(
                f"Неверный topic_id {topic_id} для канала {channel_name} от @{message.from_user.username}"
            )
            return
        await add_notification_channel(channel_id, channel_name, topic_id)
        await message.answer(
            f"Канал/группа {channel_name} добавлена для уведомлений.",
            reply_markup=keyboard,
        )
        logger.info(
            f"Канал/группа {channel_name} (ID: {channel_id}, topic_id: {topic_id}) добавлена пользователем @{message.from_user.username}"
        )
        await state.clear()
    except ValueError as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(
            f"Неверный формат ввода канала {message.text} от @{message.from_user.username}"
        )
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(
            f"Ошибка добавления канала: {str(e)} от @{message.from_user.username}"
        )


@router.callback_query(F.data == "remove_channel")
async def remove_channel_prompt(callback: CallbackQuery, **data):
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
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка удаления канала от неадминистратора @{callback.from_user.username}"
        )
        return
    channels = await get_notification_channels()
    if not channels:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text(
            "Нет каналов/групп для уведомлений.", reply_markup=keyboard
        )
        logger.info(
            f"Нет каналов для удаления, запрос от @{callback.from_user.username}"
        )
        return
    await callback.message.edit_text(
        "Выберите канал/группу для удаления:",
        reply_markup=get_remove_channel_menu(channels),
    )
    logger.debug(f"Запрос удаления канала от @{callback.from_user.username}")


@router.callback_query(F.data.startswith("remove_channel_"))
async def process_remove_channel(callback: CallbackQuery, **data):
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
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка удаления канала от неадминистратора @{callback.from_user.username}"
        )
        return
    channel_id = int(callback.data.split("_")[-1])
    async with db_pool.acquire() as conn:
        channel_name = await conn.fetchval(
            "SELECT channel_name FROM notification_channels WHERE channel_id = $1",
            channel_id,
        )
        await conn.execute(
            "DELETE FROM notification_channels WHERE channel_id = $1", channel_id
        )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]
    )
    await callback.message.edit_text(
        "Канал/группа удалена из списка уведомлений.", reply_markup=keyboard
    )
    logger.info(
        f"Канал/группа {channel_name} (ID: {channel_id}) удалена пользователем @{callback.from_user.username}"
    )


@router.callback_query(F.data == "edit_channel")
async def edit_channel_prompt(callback: CallbackQuery, **data):
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
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка редактирования канала от неадминистратора @{callback.from_user.username}"
        )
        return
    channels = await get_notification_channels()
    if not channels:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text(
            "Нет каналов/групп для редактирования.", reply_markup=keyboard
        )
        logger.info(
            f"Нет каналов для редактирования, запрос от @{callback.from_user.username}"
        )
        return
    await callback.message.edit_text(
        "Выберите канал/группу для редактирования:",
        reply_markup=get_edit_channel_menu(channels),
    )
    logger.debug(f"Запрос редактирования канала от @{callback.from_user.username}")


@router.callback_query(F.data.startswith("edit_channel_"))
async def process_edit_channel_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка редактирования канала от неадминистратора @{callback.from_user.username}"
        )
        return
    channel_id = int(callback.data.split("_")[-1])
    await state.update_data(channel_id=channel_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_channel")]
        ]
    )
    await callback.message.edit_text(
        "Введите новый topic_id (или оставьте пустым для удаления topic_id):",
        reply_markup=keyboard,
    )
    await state.set_state(AdminResponse.edit_channel)
    logger.debug(
        f"Запрос редактирования topic_id для канала ID {channel_id} от @{callback.from_user.username}"
    )


@router.message(StateFilter(AdminResponse.edit_channel))
async def process_edit_channel(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_channel")]
                ]
            ),
        )
        return
    if message.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_channel")]
            ]
        )
        await message.answer("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка редактирования канала от неадминистратора @{message.from_user.username}"
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_channel")]
        ]
    )
    try:
        topic_id = int(message.text) if message.text.strip() else None
        data_state = await state.get_data()
        channel_id = data_state["channel_id"]
        async with db_pool.acquire() as conn:
            channel_name = await conn.fetchval(
                "SELECT channel_name FROM notification_channels WHERE channel_id = $1",
                channel_id,
            )
            try:
                await message.bot.send_message(
                    chat_id=channel_id,
                    message_thread_id=topic_id,
                    text="Тестовое сообщение",
                )
            except TelegramBadRequest:
                await message.answer(
                    "Неверный topic_id или канал/группа недоступна.",
                    reply_markup=keyboard,
                )
                logger.error(
                    f"Неверный topic_id {topic_id} для канала {channel_name} от @{message.from_user.username}"
                )
                return
            await conn.execute(
                "UPDATE notification_channels SET topic_id = $1 WHERE channel_id = $2",
                topic_id,
                channel_id,
            )
        await message.answer(
            f"Канал/группа {channel_name} обновлена.", reply_markup=keyboard
        )
        logger.info(
            f"Канал/группа {channel_name} (ID: {channel_id}) обновлена с topic_id {topic_id} пользователем @{message.from_user.username}"
        )
        await state.clear()
    except ValueError:
        await message.answer(
            "Введите корректный topic_id или оставьте поле пустым.",
            reply_markup=keyboard,
        )
        logger.error(
            f"Неверный формат topic_id {message.text} для канала ID {channel_id} от @{message.from_user.username}"
        )
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}", reply_markup=keyboard)
        logger.error(
            f"Ошибка редактирования канала: {str(e)} для канала ID {channel_id} от @{message.from_user.username}"
        )


@router.callback_query(F.data == "check_employee_appeals")
async def check_employee_appeals(callback: CallbackQuery, **data):
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
        return
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка проверки заявок сотрудников от неадминистратора @{callback.from_user.username}"
        )
        return
    admins = await get_admins()
    if not admins:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]
        )
        await callback.message.edit_text(
            "Список сотрудников пуст.", reply_markup=keyboard
        )
        logger.info(
            f"Нет сотрудников для проверки, запрос от @{callback.from_user.username}"
        )
        return
    await callback.message.edit_text(
        "Выберите сотрудника для проверки заявок:",
        reply_markup=get_employee_list_menu(admins),
    )
    logger.info(f"Запрос проверки заявок сотрудников от @{callback.from_user.username}")


@router.callback_query(F.data.startswith("view_employee_appeals_"))
async def view_employee_appeals(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад", callback_data="check_employee_appeals"
                        )
                    ]
                ]
            ),
        )
        return
    admin_id = int(callback.data.split("_")[-1])
    appeals, total = await get_assigned_appeals(admin_id, page=0)
    if not appeals:
        await callback.message.edit_text(
            "У сотрудника нет заявок.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад", callback_data="check_employee_appeals"
                        )
                    ]
                ]
            ),
        )
        logger.info(
            f"Нет заявок для сотрудника ID {admin_id} по запросу от @{callback.from_user.username}"
        )
        return
    keyboard = get_my_appeals_menu(
        appeals, page=0, total_appeals=total
    )  # Используем напрямую
    await callback.message.edit_text(
        f"Заявки сотрудника (страница 1 из {max(1, (total + 9) // 10)}):",
        reply_markup=keyboard,
    )
    await state.update_data(admin_id=admin_id, appeals=appeals, total=total, page=0)
    logger.info(
        f"Показана страница 0 заявок сотрудника ID {admin_id} пользователю @{callback.from_user.username}"
    )
    await callback.answer()


@router.callback_query(F.data == "export_defect_reports")
async def export_defect_reports_prompt(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]
    )
    await callback.message.edit_text(
        "Введите диапазон серийных номеров (от <from> до <to>) или конкретный серийный номер:",
        reply_markup=keyboard,
    )
    await state.set_state(AdminResponse.report_serial_from)
    logger.debug(f"Запрос выгрузки отчётов от @{callback.from_user.username}")


@router.message(StateFilter(AdminResponse.report_serial_from))
async def process_report_serial_from(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
                ]
            ),
        )
        return
    text = message.text.strip()
    if " " in text:
        parts = text.split()
        if len(parts) == 3 and parts[1] == "до":
            serial_from = parts[0]
            serial_to = parts[2]
            await state.update_data(serial_from=serial_from, serial_to=serial_to)
        else:
            await state.update_data(serial=text)
    else:
        await state.update_data(serial=text)
    await state.clear()
    await process_export_defect_reports(message, state, db_pool=db_pool)
    logger.debug(
        f"Диапазон серийных номеров введён: {text} от @{message.from_user.username}"
    )


async def process_export_defect_reports(message: Message, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
                ]
            ),
        )
        return
    data_state = await state.get_data()
    serial = data_state.get("serial")
    serial_from = data_state.get("serial_from")
    serial_to = data_state.get("serial_to")
    reports = await get_defect_reports(serial, serial_from, serial_to)
    if not reports:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
            ]
        )
        await message.answer(
            "Нет отчётов для указанного диапазона/номера.", reply_markup=keyboard
        )
        logger.warning(
            f"Нет отчётов для диапазона {serial_from}-{serial_to} или номера {serial}, запрос от @{message.from_user.username}"
        )
        return
    data = []
    for report in reports:
        media_links = json.loads(report["media_links"] or "[]")
        photo_links = [
            media["file_id"] for media in media_links if media["type"] == "photo"
        ]
        video_links = [
            media["file_id"]
            for media in media_links
            if media["type"] in ["video", "video_note"]
        ]
        data.append(
            {
                "Serial": report["serial"],
                "Дата": report["report_date"],
                "Время": report["report_time"],
                "Место": report["location"],
                "Сотрудник ID": report["employee_id"],
                "Фото": ", ".join(photo_links),
                "Видео": ", ".join(video_links),
            }
        )
    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]
    )
    await message.answer_document(
        document=BufferedInputFile(output.getvalue(), filename="defect_reports.xlsx"),
        reply_markup=keyboard,
    )
    logger.info(
        f"Выгрузка отчётов о неисправности выполнена пользователем @{message.from_user.username}"
    )


@router.message(StateFilter(AdminResponse.defect_report_serial))
async def process_defect_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ]
        )
        await message.answer(
            "Серийный номер не может быть пустым. Попробуйте снова:",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Пустой серийный номер для отчёта о дефекте от @{message.from_user.username}"
        )
        return
    await state.update_data(serial=serial)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]
    )
    await message.answer("Введите место:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_report_location)
    logger.debug(
        f"Серийный номер {serial} для отчёта о дефекте принят от @{message.from_user.username}"
    )


@router.message(StateFilter(AdminResponse.defect_report_location))
async def process_defect_location(message: Message, state: FSMContext):
    location = message.text.strip()
    if not location:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ]
        )
        await message.answer(
            "Место не может быть пустым. Попробуйте снова:", reply_markup=keyboard
        )
        logger.warning(
            f"Пустое место для отчёта о дефекте от @{message.from_user.username}"
        )
        return
    await state.update_data(location=location)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_defect_media")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")],
        ]
    )
    await message.answer(
        "Прикрепите фото/видео (до 10, или нажмите 'Готово'):", reply_markup=keyboard
    )
    await state.set_state(AdminResponse.defect_report_media)
    await state.update_data(media_links=[])
    logger.debug(
        f"Место {location} для отчёта о дефекте принято от @{message.from_user.username}"
    )


@router.message(StateFilter(AdminResponse.defect_report_media))
async def process_defect_media(message: Message, state: FSMContext):
    data_state = await state.get_data()
    media_links = data_state.get("media_links", [])
    if len(media_links) >= 10:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Готово", callback_data="done_defect_media"
                    )
                ],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")],
            ]
        )
        await message.answer(
            "Достигнуто максимальное количество медиа (10). Нажмите 'Готово'.",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Достигнуто максимальное количество медиа для отчёта о дефекте от @{message.from_user.username}"
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_defect_media")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")],
        ]
    )
    is_valid, media = validate_media(message)
    if is_valid:
        file_id = media[0]["file_id"]
        file = await message.bot.get_file(file_id)
        file_path = file.file_path
        full_link = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        media[0]["file_id"] = full_link
        media_links.append(media[0])
        await state.update_data(media_links=media_links)
        await message.answer(
            f"Медиа добавлено ({len(media_links)}/10). Приложите ещё или нажмите 'Готово':",
            reply_markup=keyboard,
        )
        logger.debug(
            f"Медиа ({media[0]['type']}) добавлено для отчёта о дефекте от @{message.from_user.username}: {full_link}"
        )
    else:
        await message.answer(
            "Неподдерживаемый формат. Приложите фото (png/jpeg) или видео (mp4).",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Неподдерживаемый формат медиа для отчёта о дефекте от @{message.from_user.username}"
        )


@router.message(StateFilter(AdminResponse.defect_status_serial))
async def process_defect_status_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ]
        )
        await message.answer(
            "Серийный номер не может быть пустым. Попробуйте снова:",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Пустой серийный номер для изменения статуса от @{message.from_user.username}"
        )
        return
    await state.update_data(serial=serial)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Брак", callback_data="set_defect_brak")],
            [InlineKeyboardButton(text="Возврат", callback_data="set_defect_vozvrat")],
            [InlineKeyboardButton(text="Замена", callback_data="set_defect_zamena")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")],
        ]
    )
    await message.answer("Выберите статус:", reply_markup=keyboard)
    logger.debug(
        f"Серийный номер {serial} для изменения статуса принят от @{message.from_user.username}"
    )


@router.callback_query(F.data.startswith("set_defect_"))
async def set_defect_status(callback: CallbackQuery, state: FSMContext, **data):
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
        return
    data_state = await state.get_data()
    serial = data_state.get("serial")
    status = callback.data.split("_")[-1]  # brak, vozvrat, zamena
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE serials SET status = $1 WHERE serial = $2", status, serial
        )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]
    )
    await callback.message.edit_text(
        f"Статус устройства {serial} изменён на '{status}'.", reply_markup=keyboard
    )
    logger.info(
        f"Статус устройства {serial} изменён на '{status}' пользователем @{callback.from_user.username}"
    )
    await state.clear()


@router.callback_query(F.data == "done_exam_video")
async def skip_exam_video(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="done_exam_photo")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")],
        ]
    )
    await callback.message.edit_text(
        "Прикрепите фото экзаменационного листа (до 10, или 'Готово'):",
        reply_markup=keyboard,
    )
    await state.set_state(AdminResponse.exam_photo)
    await state.update_data(photo_links=[])
    logger.debug(f"Видео пропущено для экзамена от @{callback.from_user.username}")


@router.callback_query(F.data == "done_exam_photo")
async def skip_exam_photo(callback: CallbackQuery, state: FSMContext):
    data_state = await state.get_data()
    fio = data_state.get("fio", "Не указано")
    subdivision = data_state.get("subdivision", "Не указано")
    military_unit = data_state.get("military_unit", "Не указано")
    callsign = data_state.get("callsign", "Не указано")
    specialty = data_state.get("specialty", "Не указано")
    contact = data_state.get("contact", "Не указано")
    video_link = data_state.get("video_link", "Отсутствует")
    photo_links = data_state.get("photo_links", [])
    text = (
        f"Предпросмотр экзамена:\n"
        f"ФИО: {fio}\n"
        f"Подразделение: {subdivision}\n"
        f"В/Ч: {military_unit}\n"
        f"Позывной: {callsign}\n"
        f"Направление: {specialty}\n"
        f"Контакт: {contact}\n"
        f"Видео: {video_link}\n"
        f"Фото: {len(photo_links)} шт."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отправить", callback_data="submit_exam")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_exam")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)
    logger.debug(
        f"Предпросмотр экзамена: ФИО {fio}, видео {video_link}, фото {len(photo_links)} от @{callback.from_user.username}"
    )


@router.callback_query(F.data == "cancel_exam")
async def cancel_exam(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]
    )
    await callback.message.edit_text("Приём экзамена отменён.", reply_markup=keyboard)
    logger.info(f"Приём экзамена отменён пользователем @{callback.from_user.username}")


@router.callback_query(F.data == "submit_exam")
async def submit_exam(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
                ]
            ),
        )
        return
    data_state = await state.get_data()
    fio = data_state.get("fio", "")
    subdivision = data_state.get("subdivision", "")
    military_unit = data_state.get("military_unit", "")
    callsign = data_state.get("callsign", "")
    specialty = data_state.get("specialty", "")
    contact = data_state.get("contact", "")
    personal_number = data_state.get("personal_number", "")
    training_center_id = data_state.get("training_center_id")
    video_link = data_state.get("video_link", "")
    photo_links = data_state.get("photo_links", [])

    if training_center_id is None:
        await callback.message.edit_text(
            "Ошибка: не выбран учебный центр.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
                ]
            ),
        )
        await state.clear()
        logger.error(
            "Не удалось принять экзамен в submit_exam: отсутствует training_center_id"
        )
        return

    if isinstance(photo_links, str):
        try:
            photo_links = json.loads(photo_links)
        except json.JSONDecodeError:
            photo_links = [photo_links]

    if not isinstance(photo_links, list):
        photo_links = [photo_links]

    existing_exam_id = data_state.get("exam_id")
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")

    if existing_exam_id:
        await update_exam_record(
            exam_id=existing_exam_id,
            video_link=video_link,
            photo_links=photo_links,
            accepted_date=now_str,
        )
        exam_id = existing_exam_id
        result_text = "обновлён"
    else:
        exam_id = await add_exam_record(
            fio=fio,
            subdivision=subdivision,
            military_unit=military_unit,
            callsign=callsign,
            specialty=specialty,
            contact=contact,
            personal_number=personal_number,
            training_center_id=training_center_id,
            video_link=video_link,
            photo_links=photo_links,
            application_date=now_str,
            accepted_date=now_str,
        )
        result_text = "успешно добавлен"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="manage_base")]
        ]
    )
    await callback.message.edit_text(
        f"Экзамен №{exam_id} {result_text}.", reply_markup=keyboard
    )
    logger.info(
        f"Экзамен №{exam_id} {result_text} от @{callback.from_user.username}"
    )
    await state.clear()


@router.callback_query(F.data == "export_exams")
async def export_exams_handler(callback: CallbackQuery, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.delete()
        await callback.message.answer(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
                ]
            ),
        )
        return
    records = await get_exam_records()
    if not records:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="exam_menu")]
            ]
        )
        await callback.message.delete()
        await callback.message.answer("Нет данных для выгрузки.", reply_markup=keyboard)
        logger.warning(
            f"Нет данных для выгрузки экзаменов, запрос от @{callback.from_user.username}"
        )
        return
    data = []
    time_format = "%Y-%m-%dT%H:%M"

    def format_datetime(value) -> str:
        if not value:
            return "Не указана"
        try:
            return datetime.strptime(value, time_format).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value

    for record in records:
        record_dict = dict(record)
        photo_links = json.loads(record_dict.get("photo_links") or "[]")
        data.append(
            {
                "ФИО": record_dict.get("fio"),
                "Личный номер": record_dict.get("personal_number"),
                "Подразделение": record_dict.get("subdivision"),
                "В/Ч": record_dict.get("military_unit"),
                "Позывной": record_dict.get("callsign"),
                "Направление": record_dict.get("specialty"),
                "Контакт": record_dict.get("contact"),
                "УТЦ": record_dict.get("center_name") or "Отсутствует",
                "Видео": record_dict.get("video_link") or "Отсутствует",
                "Фото": ", ".join(photo_links) or "Отсутствует",
                "Дата заявки": format_datetime(record_dict.get("application_date")),
                "Дата приёма": format_datetime(record_dict.get("accepted_date")),
            }
        )
    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]
    )
    await callback.message.delete()
    await callback.message.answer_document(
        document=BufferedInputFile(output.getvalue(), filename="exam_records.xlsx"),
        reply_markup=keyboard,
    )
    logger.info(
        f"Выгрузка экзаменов выполнена пользователем @{callback.from_user.username}"
    )


@router.callback_query(F.data == "change_defect_status")
async def change_defect_status_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in MAIN_ADMIN_IDS:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ]
        )
        await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
        logger.warning(
            f"Попытка изменения статуса устройства от неадминистратора @{callback.from_user.username}"
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]
    )
    await callback.message.edit_text("Введите серийный номер:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_status_serial)
    logger.debug(
        f"Запрос изменения статуса устройства от @{callback.from_user.username}"
    )


@router.message(StateFilter(AdminResponse.defect_status_serial))
async def process_defect_status_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ]
        )
        await message.answer(
            "Серийный номер не может быть пустым. Попробуйте снова:",
            reply_markup=keyboard,
        )
        logger.warning(
            f"Пустой серийный номер для изменения статуса от @{message.from_user.username}"
        )
        return
    await state.update_data(serial=serial)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Брак", callback_data="set_defect_brak")],
            [InlineKeyboardButton(text="Возврат", callback_data="set_defect_vozvrat")],
            [InlineKeyboardButton(text="Замена", callback_data="set_defect_zamena")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")],
        ]
    )
    await message.answer("Выберите статус:", reply_markup=keyboard)
    logger.debug(
        f"Серийный номер {serial} для изменения статуса принят от @{message.from_user.username}"
    )


@router.callback_query(F.data.startswith("set_defect_"))
async def set_defect_status(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
                ]
            ),
        )
        return
    data_state = await state.get_data()
    serial = data_state.get("serial")
    status = callback.data.split("_")[-1]  # brak, vozvrat, zamena
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE serials SET status = $1 WHERE serial = $2", status, serial
        )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]
    )
    await callback.message.edit_text(
        f"Статус устройства {serial} изменён на '{status}'.", reply_markup=keyboard
    )
    logger.info(
        f"Статус устройства {serial} изменён на '{status}' пользователем @{callback.from_user.username}"
    )
    await state.clear()


@router.callback_query(F.data == "defect_menu")
async def defect_menu_prompt(callback: CallbackQuery, **data):
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
        return
    async with db_pool.acquire() as conn:
        admin_exists = await conn.fetchval(
            "SELECT 1 FROM admins WHERE admin_id = $1", callback.from_user.id
        )
        if not admin_exists and callback.from_user.id not in MAIN_ADMIN_IDS:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                ]
            )
            await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
            logger.warning(
                f"Попытка доступа к меню брака от неадминистратора @{callback.from_user.username} (ID {callback.from_user.id})"
            )
            return
        if not admin_exists and callback.from_user.id in MAIN_ADMIN_IDS:
            await add_admin(
                callback.from_user.id, callback.from_user.username or "unknown"
            )
            logger.info(
                f"Автоматически добавлен администратор ID {callback.from_user.id} (@{callback.from_user.username})"
            )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить отчёт о неисправности",
                    callback_data="add_defect_report",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить статус устройства",
                    callback_data="change_defect_status",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )
    await callback.message.edit_text("Меню брак/возврат/замена:", reply_markup=keyboard)
    logger.debug(f"Открыто меню брака от @{callback.from_user.username}")


@router.callback_query(F.data == "add_defect_report")
async def defect_report_prompt(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
                ]
            ),
        )
        return
    async with db_pool.acquire() as conn:
        admin_exists = await conn.fetchval(
            "SELECT 1 FROM admins WHERE admin_id = $1", callback.from_user.id
        )
        if not admin_exists and callback.from_user.id not in MAIN_ADMIN_IDS:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
                ]
            )
            await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
            logger.warning(
                f"Попытка добавления отчёта о дефекте от неадминистратора @{callback.from_user.username} (ID {callback.from_user.id})"
            )
            return
        if not admin_exists and callback.from_user.id in MAIN_ADMIN_IDS:
            await add_admin(
                callback.from_user.id, callback.from_user.username or "unknown"
            )
            logger.info(
                f"Автоматически добавлен администратор ID {callback.from_user.id} (@{callback.from_user.username})"
            )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]
    )
    await callback.message.edit_text("Введите серийный номер:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_report_serial)
    logger.debug(
        f"Запрос добавления отчёта о дефекте от @{callback.from_user.username}"
    )


@router.callback_query(F.data == "change_defect_status")
async def change_defect_status_prompt(
    callback: CallbackQuery, state: FSMContext, **data
):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
                ]
            ),
        )
        return
    async with db_pool.acquire() as conn:
        admin_exists = await conn.fetchval(
            "SELECT 1 FROM admins WHERE admin_id = $1", callback.from_user.id
        )
        if not admin_exists and callback.from_user.id not in MAIN_ADMIN_IDS:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
                ]
            )
            await callback.message.edit_text("Доступ запрещён.", reply_markup=keyboard)
            logger.warning(
                f"Попытка изменения статуса устройства от неадминистратора @{callback.from_user.username} (ID {callback.from_user.id})"
            )
            return
        if not admin_exists and callback.from_user.id in MAIN_ADMIN_IDS:
            await add_admin(
                callback.from_user.id, callback.from_user.username or "unknown"
            )
            logger.info(
                f"Автоматически добавлен администратор ID {callback.from_user.id} (@{callback.from_user.username})"
            )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
        ]
    )
    await callback.message.edit_text("Введите серийный номер:", reply_markup=keyboard)
    await state.set_state(AdminResponse.defect_status_serial)
    logger.debug(
        f"Запрос изменения статуса устройства от @{callback.from_user.username}"
    )


@router.callback_query(F.data == "done_defect_media")
async def done_defect_media(callback: CallbackQuery, state: FSMContext, **data):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
                ]
            ),
        )
        return
    data_state = await state.get_data()
    serial = data_state.get("serial")
    location = data_state.get("location")  # Получаем location из состояния
    report_date = datetime.now().strftime("%Y-%m-%d")
    report_time = datetime.now().strftime("%H:%M")
    media_links = data_state.get("media_links", [])
    employee_id = callback.from_user.id
    try:
        async with db_pool.acquire() as conn:
            admin_exists = await conn.fetchval(
                "SELECT 1 FROM admins WHERE admin_id = $1", employee_id
            )
            if not admin_exists and employee_id in MAIN_ADMIN_IDS:
                await add_admin(employee_id, callback.from_user.username or "unknown")
                logger.info(
                    f"Автоматически добавлен администратор ID {employee_id} (@{callback.from_user.username})"
                )
            elif not admin_exists:
                await callback.message.edit_text(
                    "Вы не зарегистрированы как администратор.",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="⬅️ Назад", callback_data="defect_menu"
                                )
                            ]
                        ]
                    ),
                )
                logger.warning(
                    f"Попытка добавления отчёта о дефекте от незарегистрированного администратора ID {employee_id}"
                )
                return
            await add_defect_report(
                serial,
                report_date,
                report_time,
                location,
                json.dumps(media_links),
                employee_id,
            )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ]
        )
        await callback.message.edit_text(
            "Отчёт о дефекте сохранён.", reply_markup=keyboard
        )
        logger.info(
            f"Отчёт о дефекте для серийника {serial} сохранён пользователем @{callback.from_user.username}"
        )
    except Exception as e:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="defect_menu")]
            ]
        )
        await callback.message.edit_text(
            f"Ошибка сохранения отчёта: {str(e)}", reply_markup=keyboard
        )
        logger.error(
            f"Ошибка сохранения отчёта о дефекте для серийника {serial}: {str(e)}"
        )
    await state.clear()


@router.callback_query(F.data.startswith("employee_appeals_page_"))
async def navigate_employee_appeals_page(
    callback: CallbackQuery, state: FSMContext, **data
):
    db_pool = data.get("db_pool")
    if not db_pool:
        logger.error("db_pool отсутствует в data")
        await callback.message.edit_text(
            "Ошибка сервера. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад", callback_data="check_employee_appeals"
                        )
                    ]
                ]
            ),
        )
        return
    page = int(callback.data.split("_")[-1])
    data_state = await state.get_data()
    admin_id = data_state.get("admin_id")
    appeals = data_state.get("appeals")
    total = data_state.get("total")
    if not appeals or total is None:
        appeals, total = await get_assigned_appeals(admin_id, page=page)
        await state.update_data(appeals=appeals, total=total)
    start_idx = page * 10
    end_idx = min(start_idx + 10, len(appeals))
    page_appeals = appeals[start_idx:end_idx]
    if not page_appeals:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="check_employee_appeals"
                    )
                ]
            ]
        )
        await callback.message.edit_text(
            "Нет заявок сотрудника.", reply_markup=keyboard
        )
        logger.info(
            f"Нет заявок для сотрудника ID {admin_id} на странице {page} для @{callback.from_user.username}"
        )
        return
    keyboard = get_my_appeals_menu(page_appeals, page, total)  # Используем напрямую
    await callback.message.edit_text(
        f"Заявки сотрудника (страница {page + 1} из {max(1, (total + 9) // 10)}):",
        reply_markup=keyboard,
    )
    await state.update_data(page=page)
    logger.info(
        f"Показана страница {page} заявок сотрудника ID {admin_id} пользователю @{callback.from_user.username}"
    )
    await callback.answer()
