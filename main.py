import asyncio
import logging
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, InputMediaPhoto, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from config import TOKEN, MAIN_ADMIN_IDS
from handlers import user_handlers, common_handlers
from handlers.admin import serial_history, appeal_actions, admin_panel, defect_management, base_management, overdue_checks, closed_appeals
from database.db import initialize_db, close_db, get_open_appeals, get_appeal, close_appeal, get_db_pool
from datetime import datetime, timedelta
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, pool):
        super().__init__()
        self.pool = pool

    async def __call__(self, handler, event, data):
        logger.debug(f"DatabaseMiddleware: Передача db_pool для события {type(event).__name__}")
        data["db_pool"] = self.pool
        return await handler(event, data)

class SerialCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, update, data):
        bot = data["bot"]
        event = update.message or update.callback_query or update.edited_message or update.channel_post or update.edited_channel_post or update.inline_query or update.chosen_inline_result or update.shipping_query or update.pre_checkout_query or update.poll or update.poll_answer or update.my_chat_member or update.chat_member or update.chat_join_request
        if event is None:
            logger.debug("Нет внутреннего события в Update, пропускаем")
            return await handler(update, data)

        user_id = None
        username = "неизвестно"
        if hasattr(event, 'from_user') and event.from_user:
            user_id = event.from_user.id
            username = event.from_user.username or "неизвестно"

        if user_id is None:
            logger.debug("Не удалось определить user_id, пропускаем событие")
            return await handler(update, data)

        logger.debug(f"SerialCheckMiddleware: Обработка события {type(event).__name__}, текст/данные: {getattr(event, 'text', getattr(event, 'data', None))}")
        state = data["state"]
        data_state = await state.get_data()
        logger.debug(f"SerialCheckMiddleware: Состояние FSM: {data_state}")
        current_state = await state.get_state()
        logger.debug(f"SerialCheckMiddleware: Текущее состояние FSM: {current_state}")

        is_admin = False
        async with data["db_pool"].acquire() as conn:
            admin = await conn.fetchrow("SELECT admin_id FROM admins WHERE admin_id = $1", user_id)
            logger.debug(f"Проверка админа для ID {user_id}: {admin}")
            if admin or user_id in MAIN_ADMIN_IDS:
                is_admin = True

        if not is_admin:
            is_confirm_auto_delete = isinstance(event, CallbackQuery) and event.data == "confirm_auto_delete"
            is_start_command = isinstance(event, Message) and event.text and event.text.startswith("/start")
            is_waiting_for_serial = current_state == "UserState:waiting_for_serial"
            if is_start_command or is_confirm_auto_delete or is_waiting_for_serial:
                logger.debug(f"Пропускаем {'/start' if is_start_command else 'confirm_auto_delete' if is_confirm_auto_delete else 'waiting_for_serial'} для пользователя @{username} (ID: {user_id})")
                return await handler(update, data)
            if "serial" not in data_state:
                logger.warning(f"Попытка доступа без серийного номера от пользователя @{username} (ID: {user_id})")
                chat_id = event.chat.id if hasattr(event, 'chat') else (event.message.chat.id if hasattr(event, 'message') else None)
                if chat_id is None:
                    logger.error("Не удалось определить chat_id для события")
                    return await handler(update, data)
                try:
                    media = [
                        InputMediaPhoto(media=FSInputFile("/data/start1.jpg")),
                        InputMediaPhoto(media=FSInputFile("/data/start2.jpg")),
                        InputMediaPhoto(media=FSInputFile("/data/start3.jpg"))
                    ]
                    text = "Для безопасности включите автоудаление сообщений через сутки и введите серийный номер заново."
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Я ВКЛЮЧИЛ АВТОУДАЛЕНИЕ", callback_data="confirm_auto_delete")]
                    ])
                    if isinstance(event, Message):
                        logger.debug(f"Отправка сообщения об автоудалении для Message от @{username} (ID: {user_id})")
                        await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
                        await bot.send_media_group(chat_id=chat_id, media=media)
                    elif isinstance(event, CallbackQuery):
                        logger.debug(f"Отправка сообщения об автоудалении для CallbackQuery от @{username} (ID: {user_id})")
                        await event.message.edit_text(text, reply_markup=keyboard)
                        await bot.send_media_group(chat_id=chat_id, media=media)
                    logger.debug(f"Сообщение об автоудалении отправлено для пользователя @{username} (ID: {user_id})")
                except (TelegramBadRequest, TelegramForbiddenError, FileNotFoundError) as e:
                    logger.error(f"Ошибка отправки сообщения об автоудалении для пользователя @{username} (ID: {user_id}): {str(e)}")
                    if isinstance(event, Message):
                        await bot.send_message(chat_id=chat_id, text="Ошибка. Попробуйте снова.")
                    elif isinstance(event, CallbackQuery):
                        await event.message.edit_text("Ошибка. Попробуйте снова.")
                return
        logger.debug(f"Пользователь @{username} (ID: {user_id}) прошёл проверку, передаём управление хэндлеру")
        return await handler(update, data)

async def check_overdue_appeals(bot):
    while True:
        try:
            db_pool = await get_db_pool()
            async with db_pool.acquire() as conn:
                appeals = await conn.fetch(
                    "SELECT appeal_id, last_response_time, user_id, admin_id FROM appeals WHERE status = 'in_progress' AND last_response_time IS NOT NULL"
                )
            for appeal in appeals:
                last_response_time = datetime.strptime(appeal['last_response_time'], "%Y-%m-%dT%H:%M")
                if datetime.now() - last_response_time > timedelta(minutes=5):  # Для теста
                    await close_appeal(appeal['appeal_id'])
                    text = f"Заявка №{appeal['appeal_id']} автоматически закрыта из-за отсутствия ответа в течение 5 минут."
                    try:
                        await bot.send_message(
                            chat_id=appeal['user_id'],
                            text=text,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                            ])
                        )
                        logger.info(f"Уведомление о закрытии заявки №{appeal['appeal_id']} отправлено пользователю ID {appeal['user_id']}")
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal['appeal_id']}: {e}")
                    if appeal['admin_id']:
                        try:
                            await bot.send_message(
                                chat_id=appeal['admin_id'],
                                text=text,
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                ])
                            )
                            logger.info(f"Уведомление о закрытии заявки №{appeal['appeal_id']} отправлено админу ID {appeal['admin_id']}")
                        except Exception as e:
                            logger.error(f"Ошибка отправки уведомления админу ID {appeal['admin_id']} для заявки №{appeal['appeal_id']}: {e}")
                    for main_admin_id in MAIN_ADMIN_IDS:
                        try:
                            await bot.send_message(
                                chat_id=main_admin_id,
                                text=text,
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
                                ])
                            )
                            logger.info(f"Уведомление о закрытии заявки №{appeal['appeal_id']} отправлено главному админу ID {main_admin_id}")
                        except Exception as e:
                            logger.error(f"Ошибка отправки уведомления главному админу ID {main_admin_id} для заявки №{appeal['appeal_id']}: {e}")
                    logger.info(f"Заявка №{appeal['appeal_id']} автоматически закрыта")
            await asyncio.sleep(60)  # Проверка каждую минуту
        except Exception as e:
            logger.error(f"Ошибка в шедулере просроченных заявок: {e}")
            await asyncio.sleep(60)

async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    pool = await initialize_db()
    dp.update.outer_middleware.register(DatabaseMiddleware(pool))
    dp.update.outer_middleware.register(SerialCheckMiddleware())
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
    asyncio.create_task(check_overdue_appeals(bot))
    try:
        await dp.start_polling(bot)
    finally:
        await close_db()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())