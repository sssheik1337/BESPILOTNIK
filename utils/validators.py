import re
from aiogram.types import Message


def validate_serial(serial):
    return bool(re.match(r"^[A-Za-z0-9]{6,20}$", str(serial)))


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
