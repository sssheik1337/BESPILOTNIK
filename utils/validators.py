import re
from aiogram.types import Message

def validate_serial(serial):
    pattern = r'^[A-Za-z0-9]{8,20}$'
    return bool(re.match(pattern, serial))

def validate_media(message: Message):
    if message.photo or message.video or message.video_note:
        if message.photo:
            return True, "photo"
        if message.video and message.video.mime_type.startswith("video/"):
            return True, "video"
        if message.video_note:
            return True, "video_note"
    return False, None