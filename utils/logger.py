import atexit
import logging
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv()

_LOGGER_NAME = "app"
_logger_configured = False
_handlers: List[logging.Handler] = []


def _resolve_log_level(level_name: str) -> int:
    level = getattr(logging, level_name.upper(), None)
    if isinstance(level, int):
        return level
    return logging.INFO


def _configure_logger() -> logging.Logger:
    global _logger_configured

    base_logger = logging.getLogger(_LOGGER_NAME)
    if base_logger.handlers:
        return base_logger

    if _logger_configured:
        return base_logger

    log_level = _resolve_log_level(os.getenv("LOG_LEVEL", "INFO"))
    log_dir_env = os.getenv("LOG_DIR", "/opt/bespilotnik/logs")
    log_dir = Path(log_dir_env).expanduser().resolve()
    os.makedirs(log_dir, exist_ok=True)

    rotation_mode = os.getenv("LOG_ROTATION_MODE", "size").lower()
    max_bytes = int(os.getenv("LOG_MAX_BYTES", "10485760"))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "7"))
    time_rotation = os.getenv("LOG_TIME_ROTATION", "midnight")
    time_rotation_interval = int(os.getenv("LOG_TIME_ROTATION_INTERVAL", "1"))

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    base_logger.setLevel(log_level)
    base_logger.propagate = False

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)

    main_log_path = log_dir / "bot.log"
    if rotation_mode == "time":
        file_handler: logging.Handler = TimedRotatingFileHandler(
            main_log_path,
            when=time_rotation,
            interval=time_rotation_interval,
            backupCount=backup_count,
            encoding="utf-8",
        )
    else:
        file_handler = RotatingFileHandler(
            main_log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    error_handler = logging.FileHandler(log_dir / "bot_error.log", encoding="utf-8")
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)

    handlers: Dict[str, logging.Handler] = {
        "stream": stream_handler,
        "file": file_handler,
        "error": error_handler,
    }

    for handler in handlers.values():
        base_logger.addHandler(handler)
        _handlers.append(handler)

    def _close_handlers() -> None:
        for handler in _handlers:
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass

    atexit.register(_close_handlers)

    _logger_configured = True
    return base_logger


def get_logger(name: str) -> logging.Logger:
    _configure_logger()
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
