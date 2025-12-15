import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_MODE = os.getenv("BOT_MODE", "PROD").strip().upper()
LOCAL_BOT_API_HOST = os.getenv("LOCAL_BOT_API_HOST", "").strip()
LOCAL_BOT_API_REMOTE_DIR = os.getenv("LOCAL_BOT_API_REMOTE_DIR", "").strip()
# Укажи путь к примонтированному каталогу данных Telegram Bot API на хосте,
# если контейнер запущен с флагом --local. Например:
# LOCAL_BOT_API_DATA_DIR = r"C:\\TelegramBotApiData"
LOCAL_BOT_API_DATA_DIR = os.getenv("LOCAL_BOT_API_DATA_DIR")
# Каталог для локального кеша загруженных файлов (используется для сжатия видео и резервных копий)
LOCAL_BOT_API_CACHE_DIR = os.getenv("LOCAL_BOT_API_CACHE_DIR", "").strip()
NGROK_PUBLIC_URL = os.getenv("NGROK_PUBLIC_URL", "").strip()
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook").strip()
PUBLIC_MEDIA_ROOT = os.getenv("PUBLIC_MEDIA_ROOT", "").strip()

WEBHOOK_URL = (
    f"{NGROK_PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}" if NGROK_PUBLIC_URL else ""
)
PUBLIC_MEDIA_URL = f"{NGROK_PUBLIC_URL.rstrip('/')}/files" if NGROK_PUBLIC_URL else ""
EXAM_MEDIA_ROOT = f"{PUBLIC_MEDIA_ROOT}/exams" if PUBLIC_MEDIA_ROOT else ""
EXAM_VIDEOS_DIR = f"{EXAM_MEDIA_ROOT}/videos" if EXAM_MEDIA_ROOT else ""
EXAM_PHOTOS_DIR = f"{EXAM_MEDIA_ROOT}/photos" if EXAM_MEDIA_ROOT else ""
DEFECT_MEDIA_DIR = f"{PUBLIC_MEDIA_ROOT}/defects" if PUBLIC_MEDIA_ROOT else ""
MANUALS_STORAGE_DIR = f"{PUBLIC_MEDIA_ROOT}/manuals" if PUBLIC_MEDIA_ROOT else ""
VISITS_MEDIA_DIR = f"{PUBLIC_MEDIA_ROOT}/visits" if PUBLIC_MEDIA_ROOT else ""
API_BASE_URL = f"{LOCAL_BOT_API_HOST.rstrip('/')}/bot{{token}}/" if LOCAL_BOT_API_HOST else ""
API_FILE_BASE_URL = (
    f"{LOCAL_BOT_API_HOST.rstrip('/')}/file/bot{{token}}/" if LOCAL_BOT_API_HOST else ""
)
MAIN_ADMIN_IDS = [
    int(admin_id)
    for admin_id in os.getenv("MAIN_ADMIN_IDS", "").split(",")
    if admin_id.strip().isdigit()
]

DB_CONFIG = {
    "user": os.getenv("POSTGRES_USER", "").strip(),
    "password": os.getenv("POSTGRES_PASSWORD", "").strip(),
    "database": os.getenv("POSTGRES_DB", "").strip(),
    "host": os.getenv("POSTGRES_HOST", "").strip(),
    "port": os.getenv("POSTGRES_PORT", "").strip(),
}
