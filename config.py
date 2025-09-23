TOKEN = "8133341294:AAEzBVr7n-K5D-70pY4IZXlaBUH1J2Nlh2A"
LOCAL_BOT_API_HOST = "http://localhost:8081"
LOCAL_BOT_API_REMOTE_DIR = "/var/lib/telegram-bot-api"
# Укажи путь к примонтированному каталогу данных Telegram Bot API на хосте,
# если контейнер запущен с флагом --local. Например:
# LOCAL_BOT_API_DATA_DIR = r"C:\\TelegramBotApiData"
LOCAL_BOT_API_DATA_DIR = None
# Каталог для локального кеша загруженных файлов (используется для сжатия видео и резервных копий)
LOCAL_BOT_API_CACHE_DIR = "data/telegram_files"
NGROK_PUBLIC_URL = "https://10bdf31051e0.ngrok-free.app"  # Замени на адрес от ngrok
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{NGROK_PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
PUBLIC_MEDIA_ROOT = "data"
PUBLIC_MEDIA_URL = f"{NGROK_PUBLIC_URL.rstrip('/')}/files"
EXAM_MEDIA_ROOT = f"{PUBLIC_MEDIA_ROOT}/exams"
EXAM_VIDEOS_DIR = f"{EXAM_MEDIA_ROOT}/videos"
EXAM_PHOTOS_DIR = f"{EXAM_MEDIA_ROOT}/photos"
DEFECT_MEDIA_DIR = f"{PUBLIC_MEDIA_ROOT}/defects"
MANUALS_STORAGE_DIR = f"{PUBLIC_MEDIA_ROOT}/manuals"
API_BASE_URL = f"{LOCAL_BOT_API_HOST}/bot{{token}}/"
API_FILE_BASE_URL = f"{LOCAL_BOT_API_HOST}/file/bot{{token}}/"
MAIN_ADMIN_IDS = [7797651918]  # ID главных админов
DB_PATH = "/data/bot.db"  # Путь к SQLite базе

DB_CONFIG = {
    "user": "postgres",
    "password": "Merryweather4670!",
    "database": "musorok",
    "host": "localhost",
    "port": 5432,
}
