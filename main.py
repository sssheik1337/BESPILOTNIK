import asyncio
import logging
from pathlib import Path
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from config import TOKEN, API_BASE_URL, WEBHOOK_URL, MAIN_ADMIN_IDS, LOG_FILE_PATH
from urllib.parse import quote

from utils.storage import ensure_within_public_root, public_root
from handlers import user_handlers, common_handlers, user_exam
from handlers.admin import (
    serial_history,
    appeal_actions,
    admin_panel,
    defect_management,
    base_management,
    overdue_checks,
    closed_appeals,
    manuals_management,
)
from database.db import initialize_db, close_db, get_open_appeals, close_appeal
from aiogram.client.session.aiohttp import AiohttpSession
from datetime import datetime

log_path = Path(LOG_FILE_PATH)
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
)
logging.getLogger("aiohttp.server").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

db_lock = asyncio.Lock()


class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, pool):
        super().__init__()
        self.pool = pool

    async def __call__(self, handler, event, data):
        logger.debug(
            f"DatabaseMiddleware: Передача db_pool для события {type(event).__name__}"
        )
        data["db_pool"] = self.pool
        return await handler(event, data)


class SerialCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, update, data):
        bot = data["bot"]
        event = (
            update.message
            or update.callback_query
            or update.edited_message
            or update.channel_post
            or update.edited_channel_post
            or update.inline_query
            or update.chosen_inline_result
            or update.shipping_query
            or update.pre_checkout_query
            or update.poll
            or update.poll_answer
            or update.my_chat_member
            or update.chat_member
            or update.chat_join_request
        )
        if event is None:
            logger.debug("Нет внутреннего события в Update, пропускаем")
            return await handler(update, data)

        user_id = None
        username = "неизвестно"

        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.id
            username = event.from_user.username or "неизвестно"

        state = data.get("state")
        if state is None:
            logger.debug(
                "FSM context is unavailable for событие %s, пропускаем проверку серийника",
                type(event).__name__,
            )
            return await handler(update, data)

        try:
            current_state = await state.get_state()
        except Exception as exc:  # pragma: no cover - защитная логика на случай ошибок FSM
            logger.warning(
                "Не удалось получить состояние FSM (%s) для пользователя %s (ID %s): %s",
                type(event).__name__,
                f"@{username}",
                user_id,
                exc,
            )
            return await handler(update, data)

        logger.debug(f"SerialCheckMiddleware: Текущее состояние FSM: {current_state}")

        if current_state and current_state.startswith("VisitState:"):
            logger.debug(
                "Передаём сообщение в VisitState без дополнительных проверок для пользователя @%s (ID: %s)",
                username,
                user_id,
            )
            return await handler(update, data)

        if not hasattr(event, "chat"):
            logger.debug(f"Пропускаем событие {type(event).__name__} без чата")
            return await handler(update, data)

        user_id = None
        username = "неизвестно"
        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.id
            username = event.from_user.username or "неизвестно"

        if user_id is None:
            logger.debug("Не удалось определить user_id, пропускаем событие")
            return await handler(update, data)

        if isinstance(event, Message):
            if event.text and event.text.startswith("/"):
                logger.debug(
                    "Обработка команды '%s' от @%s (ID: %s) в чате типа %s",
                    event.text,
                    username,
                    user_id,
                    event.chat.type,
                )
            else:
                logger.debug(
                    "Передаём текстовое сообщение '%s' от @%s (ID: %s) в чате типа %s",
                    event.text,
                    username,
                    user_id,
                    event.chat.type,
                )
            return await handler(update, data)

        if isinstance(event, CallbackQuery):
            logger.debug(
                f"Пропускаем CallbackQuery для пользователя @{username} (ID: {user_id}) в чате типа {event.chat.type}"
            )
            return await handler(update, data)

        logger.debug(
            f"Игнорируем событие {type(event).__name__} от @{username} (ID: {user_id}) в чате типа {event.chat.type}"
        )
        return await handler(update, data)


async def check_overdue_appeals(bot: Bot):
    while True:
        try:
            async with db_lock:
                result = await get_open_appeals(page=0)
                if result is None:
                    logger.warning("get_open_appeals вернул None, пропускаем итерацию")
                    await asyncio.sleep(3600)
                    continue
                appeals, _ = result
                for appeal in appeals:
                    created_time = datetime.strptime(
                        appeal["created_time"], "%Y-%m-%dT%H:%M"
                    )
                    if (datetime.now() - created_time).days > 30 and appeal[
                        "status"
                    ] == "new":
                        await close_appeal(appeal["appeal_id"])
                        text = f"Заявка №{appeal['appeal_id']} автоматически закрыта по истечении 30 дней."
                        try:
                            await bot.send_message(
                                chat_id=appeal["user_id"],
                                text=text,
                                reply_markup=InlineKeyboardMarkup(
                                    inline_keyboard=[
                                        [
                                            InlineKeyboardButton(
                                                text="⬅️ Назад",
                                                callback_data="main_menu",
                                            )
                                        ]
                                    ]
                                ),
                            )
                            logger.info(
                                f"Уведомление о закрытии заявки №{appeal['appeal_id']} отправлено пользователю ID {appeal['user_id']}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Ошибка отправки уведомления пользователю ID {appeal['user_id']} для заявки №{appeal['appeal_id']}: {e}"
                            )
                        if appeal["admin_id"]:
                            try:
                                await bot.send_message(
                                    chat_id=appeal["admin_id"],
                                    text=text,
                                    reply_markup=InlineKeyboardMarkup(
                                        inline_keyboard=[
                                            [
                                                InlineKeyboardButton(
                                                    text="⬅️ Назад",
                                                    callback_data="main_menu",
                                                )
                                            ]
                                        ]
                                    ),
                                )
                                logger.info(
                                    f"Уведомление о закрытии заявки №{appeal['appeal_id']} отправлено админу ID {appeal['admin_id']}"
                                )
                            except Exception as e:
                                logger.error(
                                    f"Ошибка отправки уведомления админу ID {appeal['admin_id']} для заявки №{appeal['appeal_id']}: {e}"
                                )
                        for main_admin_id in MAIN_ADMIN_IDS:
                            if (
                                not appeal["admin_id"]
                                or main_admin_id != appeal["admin_id"]
                            ):
                                try:
                                    await bot.send_message(
                                        chat_id=main_admin_id,
                                        text=text,
                                        reply_markup=InlineKeyboardMarkup(
                                            inline_keyboard=[
                                                [
                                                    InlineKeyboardButton(
                                                        text="⬅️ Назад",
                                                        callback_data="main_menu",
                                                    )
                                                ]
                                            ]
                                        ),
                                    )
                                    logger.info(
                                        f"Уведомление о закрытии заявки №{appeal['appeal_id']} отправлено главному админу ID {main_admin_id}"
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"Ошибка отправки уведомления главному админу ID {main_admin_id} для заявки №{appeal['appeal_id']}: {e}"
                                    )
                        logger.info(
                            f"Заявка №{appeal['appeal_id']} автоматически закрыта"
                        )
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Ошибка в шедулере просроченных заявок: {e}")
            await asyncio.sleep(3600)


async def handle_root(request):
    return web.Response(status=404)


async def serve_public_file(request: web.Request) -> web.StreamResponse:
    path_fragment = request.match_info.get("path", "").strip()
    if not path_fragment:
        raise web.HTTPNotFound()

    candidate = public_root() / Path(path_fragment)

    try:
        ensure_within_public_root(candidate)
    except ValueError:
        logger.warning("Попытка доступа к файлу вне публичного каталога: %s", candidate)
        raise web.HTTPNotFound() from None

    if not candidate.exists() or not candidate.is_file():
        raise web.HTTPNotFound()

    response = web.FileResponse(path=candidate)
    safe_name = quote(candidate.name)
    response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{safe_name}"
    return response


async def on_startup(app):
    bot = app["bot"]
    dp = app["dp"]
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    pool = await initialize_db()
    dp.update.outer_middleware.register(DatabaseMiddleware(pool))
    dp.update.outer_middleware.register(SerialCheckMiddleware())
    asyncio.create_task(check_overdue_appeals(bot))

    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await bot.set_my_commands(
        [BotCommand(command="start", description="Главное меню")],
        scope=BotCommandScopeDefault(),
    )
    logger.info("Команды бота обновлены и кнопка меню установлена")


async def on_shutdown(app):
    bot = app["bot"]
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.session.close()
    await close_db()
    logger.info("Webhook удалён, сессия закрыта")


def main():
    global bot, dp
    bot = Bot(
        token=TOKEN, session=AiohttpSession(), base_url=API_BASE_URL.format(token=TOKEN)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_panel.router)
    dp.include_router(user_handlers.router)
    dp.include_router(common_handlers.router)
    dp.include_router(user_exam.router)
    dp.include_router(serial_history.router)
    dp.include_router(appeal_actions.router)
    dp.include_router(defect_management.router)
    dp.include_router(base_management.router)
    dp.include_router(overdue_checks.router)
    dp.include_router(closed_appeals.router)
    dp.include_router(manuals_management.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app.router.add_get("/", handle_root)
    app.router.add_route("GET", "/files/{path:.*}", serve_public_file)
    app.router.add_route("HEAD", "/files/{path:.*}", serve_public_file)
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    logger.info("Бот запущен в режиме Webhook")
    web.run_app(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiohttp import web

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )
    main()
