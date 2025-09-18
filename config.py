TOKEN = "8133341294:AAEzBVr7n-K5D-70pY4IZXlaBUH1J2Nlh2A"
API_BASE_URL = "http://localhost:8080/bot{token}/"
NGROK_PUBLIC_URL = "https://10bdf31051e0.ngrok-free.app"  # Замени на адрес от ngrok
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{NGROK_PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
MAIN_ADMIN_IDS = [7797651918]  # ID главных админов
DB_PATH = "/data/bot.db"  # Путь к SQLite базе

DB_CONFIG = {
    "user": "postgres",
    "password": "Merryweather4670!",
    "database": "musorok",
    "host": "localhost",
    "port": 5432,
}
