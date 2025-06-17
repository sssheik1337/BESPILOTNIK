# db.py
import asyncpg
from datetime import datetime, timedelta
import json
from config import DB_CONFIG
import logging

logger = logging.getLogger(__name__)

pool = None

async def initialize_db():
    global pool
    try:
        logger.debug(f"Connecting to PostgreSQL with config: {DB_CONFIG}")
        pool = await asyncpg.create_pool(**DB_CONFIG)
        if pool is None:
            logger.error("Failed to create database pool: pool is None")
            raise RuntimeError("Failed to create database pool: pool is None")
        logger.debug("Successfully connected to PostgreSQL")
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        logger.debug("Test query executed successfully")
        await create_tables()
        logger.info("Подключение к базе данных PostgreSQL установлено")
        return pool
    except Exception as e:
        logger.error(f"Ошибка подключения к базе данных PostgreSQL: {e}")
        raise

async def get_db_pool():
    global pool
    if pool is None:
        raise RuntimeError("Database pool is not initialized")
    return pool

async def close_db():
    global pool
    if pool:
        await pool.close()
        logger.info("Пул соединений к базе данных закрыт")
        pool = None

async def create_tables():
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS serials (
                serial TEXT PRIMARY KEY,
                upload_date TEXT,
                appeal_count INTEGER DEFAULT 0,
                status TEXT,
                return_status TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                appeal_id SERIAL PRIMARY KEY,
                serial TEXT,
                username TEXT,
                description TEXT,
                media_files TEXT,
                status TEXT,
                admin_id BIGINT,
                user_id BIGINT,
                created_time TEXT,
                taken_time TEXT,
                closed_time TEXT,
                response TEXT,
                FOREIGN KEY (serial) REFERENCES serials (serial)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id BIGINT PRIMARY KEY,
                username TEXT,
                appeals_taken INTEGER DEFAULT 0,
                is_main_admin BOOLEAN DEFAULT FALSE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_channels (
                channel_id BIGINT PRIMARY KEY,
                channel_name TEXT,
                topic_id INTEGER
            )
        """)
    logger.info("Таблицы базы данных созданы или проверены")

async def add_serial(serial):
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO serials (serial, upload_date, status) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                serial, datetime.now().isoformat(), "active"
            )
            rowcount = await conn.fetchval("SELECT COUNT(*) FROM serials WHERE serial = $1", serial)
            if rowcount == 0:
                logger.debug(f"Серийный номер {serial} уже существует в базе")
            else:
                logger.info(f"Серийный номер {serial} добавлен в базу")
        except Exception as e:
            logger.error(f"Ошибка при добавлении серийного номера {serial}: {e}")
            raise

async def add_appeal(serial, username, description, media_files, user_id):
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                result = await conn.fetchrow(
                    "INSERT INTO appeals (serial, username, description, media_files, status, user_id, created_time) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING appeal_id",
                    serial, username, description, json.dumps(media_files), "new", user_id, datetime.now().isoformat()
                )
                appeal_id = result['appeal_id']
                await conn.execute(
                    "UPDATE serials SET appeal_count = appeal_count + 1 WHERE serial = $1",
                    serial
                )
                appeal_count = await conn.fetchval("SELECT appeal_count FROM serials WHERE serial = $1", serial)
                logger.info(f"Заявка №{appeal_id} создана для серийника {serial} пользователем @{username} (ID: {user_id})")
                return appeal_id, appeal_count
        except Exception as e:
            logger.error(f"Ошибка при создании заявки для серийника {serial}: {e}")
            raise

async def check_duplicate_appeal(serial, description, user_id):
    async with pool.acquire() as conn:
        time_threshold = (datetime.now() - timedelta(hours=24)).isoformat()
        result = await conn.fetchrow(
            "SELECT * FROM appeals WHERE serial = $1 AND description = $2 AND user_id = $3 "
            "AND status IN ('new', 'in_progress', 'postponed') AND created_time >= $4",
            serial, description, user_id, time_threshold
        )
        if result:
            logger.warning(f"Обнаружена дублирующая заявка для серийника {serial} от пользователя ID {user_id}")
        return result

async def take_appeal(appeal_id, admin_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE appeals SET status = $1, admin_id = $2, taken_time = $3 WHERE appeal_id = $4",
                "in_progress", admin_id, datetime.now().isoformat(), appeal_id
            )
            await conn.execute(
                "UPDATE admins SET appeals_taken = appeals_taken + 1 WHERE admin_id = $1",
                admin_id
            )
            logger.info(f"Заявка №{appeal_id} взята в работу сотрудником ID {admin_id}")

async def delegate_appeal(appeal_id, new_admin_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            admin = await conn.fetchrow("SELECT * FROM admins WHERE admin_id = $1", new_admin_id)
            if not admin:
                logger.error(f"Сотрудник с ID {new_admin_id} не найден")
                raise ValueError("Сотрудник не найден")
            await conn.execute(
                "UPDATE appeals SET admin_id = $1, status = $2 WHERE appeal_id = $3",
                new_admin_id, "in_progress", appeal_id
            )
            logger.info(f"Заявка №{appeal_id} делегирована сотруднику ID {new_admin_id} со статусом 'in_progress'")

async def close_appeal(appeal_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE appeals SET status = $1, closed_time = $2 WHERE appeal_id = $3",
            "processed", datetime.now().isoformat(), appeal_id
        )
        logger.info(f"Заявка №{appeal_id} закрыта")

async def save_response(appeal_id, response):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE appeals SET response = $1 WHERE appeal_id = $2",
            response, appeal_id
        )
        logger.debug(f"Ответ сохранён для заявки №{appeal_id}: {response}")
        logger.info(f"Ответ для заявки №{appeal_id} сохранён в базе данных")

async def postpone_appeal(appeal_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE appeals SET status = $1 WHERE appeal_id = $2",
            "postponed", appeal_id
        )
        logger.info(f"Заявка №{appeal_id} отложена")

async def get_appeal(appeal_id):
    async with pool.acquire() as conn:
        appeal = await conn.fetchrow("SELECT * FROM appeals WHERE appeal_id = $1", appeal_id)
        logger.debug(f"Запрос заявки №{appeal_id}, найдена: {bool(appeal)}")
        return appeal

async def get_serial_history(serial):
    async with pool.acquire() as conn:
        serial_data = await conn.fetchrow(
            "SELECT appeal_count, return_status, upload_date FROM serials WHERE serial = $1", serial
        )
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE serial = $1 ORDER BY taken_time DESC, appeal_id DESC", serial
        )
        logger.info(f"История серийника {serial} запрошена, найдено обращений: {len(appeals)}")
        return serial_data, appeals

async def add_admin(admin_id, username, is_main_admin=False):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (admin_id, username, is_main_admin) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            admin_id, username, is_main_admin
        )
        logger.info(f"Сотрудник @{username} (admin_id: {admin_id}, is_main_admin: {is_main_admin}) добавлен в базу")

async def add_notification_channel(channel_id, channel_name, topic_id=None):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO notification_channels (channel_id, channel_name, topic_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            channel_id, channel_name, topic_id
        )
        logger.info(f"Канал {channel_name} (ID: {channel_id}, topic_id: {topic_id}) добавлен для уведомлений")

async def get_notification_channels():
    async with pool.acquire() as conn:
        channels = await conn.fetch("SELECT * FROM notification_channels")
        logger.debug(f"Запрошены каналы уведомлений, найдено: {len(channels)}")
        return channels

async def get_assigned_appeals(admin_id):
    async with pool.acquire() as conn:
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE admin_id = $1 AND status IN ('in_progress', 'postponed')", admin_id
        )
        logger.info(f"Запрошены заявки сотрудника ID {admin_id}, найдено: {len(appeals)}")
        return appeals

async def get_user_appeals(user_id):
    async with pool.acquire() as conn:
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE user_id = $1 ORDER BY created_time DESC", user_id
        )
        logger.info(f"Запрошены заявки пользователя ID {user_id}, найдено: {len(appeals)}")
        return appeals

async def get_open_appeals(admin_id):
    async with pool.acquire() as conn:
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE status IN ('new', 'postponed', 'overdue') AND (admin_id IS NULL OR admin_id != $1)",
            admin_id
        )
        logger.info(f"Запрошены открытые заявки для сотрудника ID {admin_id}, найдено: {len(appeals)}")
        return appeals