import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "TELEGRAM TOKEN")
LOCAL_BOT_API_HOST = os.getenv("LOCAL_BOT_API_HOST", "http://localhost:8081")
LOCAL_BOT_API_REMOTE_DIR = os.getenv("LOCAL_BOT_API_REMOTE_DIR", "/var/lib/telegram-bot-api")
# Укажи путь к примонтированному каталогу данных Telegram Bot API на хосте,
# если контейнер запущен с флагом --local. Например:
# LOCAL_BOT_API_DATA_DIR = r"C:\\TelegramBotApiData"
LOCAL_BOT_API_DATA_DIR = os.getenv("LOCAL_BOT_API_DATA_DIR")
# Каталог для локального кеша загруженных файлов (используется для сжатия видео и резервных копий)
LOCAL_BOT_API_CACHE_DIR = os.getenv("LOCAL_BOT_API_CACHE_DIR", "data/telegram_files")
NGROK_PUBLIC_URL = os.getenv("NGROK_PUBLIC_URL", "https://10bdf31051e0.ngrok-free.app")  # Замени на адрес от ngrok
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
PUBLIC_MEDIA_ROOT = os.getenv("PUBLIC_MEDIA_ROOT", "data")

WEBHOOK_URL = f"{NGROK_PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
PUBLIC_MEDIA_URL = f"{NGROK_PUBLIC_URL.rstrip('/')}/files"
EXAM_MEDIA_ROOT = f"{PUBLIC_MEDIA_ROOT}/exams"
EXAM_VIDEOS_DIR = f"{EXAM_MEDIA_ROOT}/videos"
EXAM_PHOTOS_DIR = f"{EXAM_MEDIA_ROOT}/photos"
DEFECT_MEDIA_DIR = f"{PUBLIC_MEDIA_ROOT}/defects"
MANUALS_STORAGE_DIR = f"{PUBLIC_MEDIA_ROOT}/manuals"
VISITS_MEDIA_DIR = f"{PUBLIC_MEDIA_ROOT}/visits"
API_BASE_URL = f"{LOCAL_BOT_API_HOST.rstrip('/')}/bot{{token}}/"
API_FILE_BASE_URL = f"{LOCAL_BOT_API_HOST.rstrip('/')}/file/bot{{token}}/"
LOG_FILE_PATH = f"{LOCAL_BOT_API_CACHE_DIR}/bot_err.log"
MAIN_ADMIN_IDS = [
    int(admin_id)
    for admin_id in os.getenv("MAIN_ADMIN_IDS", "7797651918").split(",")
    if admin_id.strip().isdigit()
]

DB_CONFIG = {
    "user": os.getenv("POSTGRES_USER", "пользователь"),
    "password": os.getenv("POSTGRES_PASSWORD", "пароль бд"),
    "database": os.getenv("POSTGRES_DB", "имя бд"),
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT", "сюда порт"),
}
