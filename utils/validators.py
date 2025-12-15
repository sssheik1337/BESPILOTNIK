import re

from aiogram.types import Message


PERSONAL_NUMBER_PATTERN = re.compile(r"^[\w\sА-Яа-я-]{2,30}$")
MILITARY_UNIT_PATTERN = re.compile(r"^[\w\sА-Яа-я/-]{2,40}$")
SUBDIVISION_PATTERN = re.compile(r"^[\w\sА-Яа-я-]{2,60}$")
CALLSIGN_PATTERN = re.compile(r"^[\w\sА-Яа-я-]{2,30}$")


def validate_serial(serial):
    return bool(re.match(r"^[A-Za-z0-9]{6,20}$", str(serial)))


def is_valid_personal_number(value: str) -> bool:
    if not value:
        return False
    return bool(PERSONAL_NUMBER_PATTERN.match(value.strip()))


def is_valid_military_unit(value: str) -> bool:
    if not value:
        return False
    return bool(MILITARY_UNIT_PATTERN.match(value.strip()))


def is_valid_subdivision(value: str) -> bool:
    if not value:
        return False
    return bool(SUBDIVISION_PATTERN.match(value.strip()))


def is_valid_callsign(value: str) -> bool:
    if not value:
        return False
    return bool(CALLSIGN_PATTERN.match(value.strip()))


def validate_media(message: Message, max_files=10, max_size_mb=200):
    if message.media_group_id or message.photo or message.video or message.video_note:
        valid_types = ["image/png", "image/jpeg", "video/mp4"]
        media = []
        if message.photo:
            file = message.photo[-1]
            mime_type = (
                "image/jpeg"  # Telegram не возвращает mime для photo, считаем jpeg
            )
            if file.file_size / (1024 * 1024) <= max_size_mb:
                media.append(
                    {"type": "photo", "file_id": file.file_id, "mime_type": mime_type}
                )
        elif message.video and message.video.mime_type in valid_types:
            if message.video.file_size / (1024 * 1024) <= max_size_mb:
                media.append(
                    {
                        "type": "video",
                        "file_id": message.video.file_id,
                        "mime_type": message.video.mime_type,
                    }
                )
        elif message.video_note:
            mime_type = "video/mp4"  # Кружки всегда mp4
            if message.video_note.file_size / (1024 * 1024) <= max_size_mb:
                media.append(
                    {
                        "type": "video_note",
                        "file_id": message.video_note.file_id,
                        "mime_type": mime_type,
                    }
                )
        return bool(media), media
    return False, None
