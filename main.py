import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import TOKEN
from handlers import user_handlers, admin_handlers, common_handlers

# Указываем абсолютный путь для файла логов
LOG_FILE_PATH = "/data/bot.log"

# Проверяем, существует ли директория /data, и создаём её, если нет
os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),  # Используем абсолютный путь
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(common_handlers.router)

    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())