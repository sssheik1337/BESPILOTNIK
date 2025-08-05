import asyncio
import logging
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.fsm.storage.memory import MemoryStorage
from config import TOKEN
from handlers import user_handlers, common_handlers
from handlers.admin import serial_history, appeal_actions, admin_panel, defect_management, base_management, overdue_checks, closed_appeals
from database.db import initialize_db, close_db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/data/bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Middleware для инъекции пула соединений
class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, pool):
        super().__init__()
        self.pool = pool

    async def __call__(self, handler, event, data):
        data["db_pool"] = self.pool
        return await handler(event, data)

async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    pool = await initialize_db()
    dp.update.outer_middleware.register(DatabaseMiddleware(pool))
    dp.include_router(user_handlers.router)
    dp.include_router(common_handlers.router)
    dp.include_router(serial_history.router)
    dp.include_router(appeal_actions.router)
    dp.include_router(admin_panel.router)
    dp.include_router(defect_management.router)
    dp.include_router(base_management.router)
    dp.include_router(overdue_checks.router)
    dp.include_router(closed_appeals.router)
    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
        await bot.session.close()




if __name__ == "__main__":
    asyncio.run(main())