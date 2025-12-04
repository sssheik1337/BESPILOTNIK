"""Единый модуль настройки логирования."""
import logging
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

_LOGGER_CONFIGURED = False


def _resolve_log_dir() -> Path:
    """Возвращает абсолютный путь к каталогу логов и создаёт его при необходимости."""
    raw_dir = os.getenv("LOG_DIR", "/opt/bespilotnik/logs")
    log_dir = Path(raw_dir).expanduser()
    if not log_dir.is_absolute():
        log_dir = log_dir.resolve()
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _build_handlers(log_dir: Path, level: int) -> list[logging.Handler]:
    """Формирует список обработчиков логирования."""
    rotation_mode = os.getenv("LOG_ROTATION_MODE", "size").lower()
    max_bytes = int(os.getenv("LOG_MAX_BYTES", "10485760"))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "7"))
    time_rotation = os.getenv("LOG_TIME_ROTATION", "midnight")
    time_rotation_interval = int(os.getenv("LOG_TIME_ROTATION_INTERVAL", "1"))

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    handlers: list[logging.Handler] = []

    stdout_handler = logging.StreamHandler()
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(formatter)
    handlers.append(stdout_handler)

    log_file = log_dir / "bot.log"
    error_file = log_dir / "bot_error.log"

    if rotation_mode == "time":
        file_handler: logging.Handler = TimedRotatingFileHandler(
            log_file,
            when=time_rotation,
            interval=time_rotation_interval,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler: logging.Handler = TimedRotatingFileHandler(
            error_file,
            when=time_rotation,
            interval=time_rotation_interval,
            backupCount=backup_count,
            encoding="utf-8",
        )
    else:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler = RotatingFileHandler(
            error_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )

    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)

    handlers.extend([file_handler, error_handler])
    return handlers


def _configure_root_logger() -> None:
    """Конфигурирует корневой логгер один раз за процесс."""
    global _LOGGER_CONFIGURED
    if _LOGGER_CONFIGURED:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO

    root_logger = logging.getLogger()
    if root_logger.handlers:
        _LOGGER_CONFIGURED = True
        return

    log_dir = _resolve_log_dir()

    root_logger.setLevel(level)

    handlers = _build_handlers(log_dir, level)

    for handler in handlers:
        root_logger.addHandler(handler)

    # Подавляем избыточный лог aiohttp в info-режиме
    logging.getLogger("aiohttp.server").setLevel(logging.WARNING)

    _LOGGER_CONFIGURED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Возвращает настроенный логгер с указанным именем."""
    _configure_root_logger()
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.propagate = True
    return logger
