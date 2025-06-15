import aiosqlite
from datetime import datetime, timedelta
import json
from config import DB_PATH
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db_path = DB_PATH

    async def connect(self):
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.create_tables()

    async def create_tables(self):
        async with self.conn.cursor() as cursor:
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS serials (
                    serial TEXT PRIMARY KEY,
                    upload_date TEXT,
                    appeal_count INTEGER DEFAULT 0,
                    status TEXT,
                    return_status TEXT
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS appeals (
                    appeal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial TEXT,
                    username TEXT,
                    description TEXT,
                    media_files TEXT,
                    status TEXT,
                    admin_id INTEGER,
                    user_id INTEGER,
                    created_time TEXT,
                    taken_time TEXT,
                    closed_time TEXT,
                    response TEXT,
                    FOREIGN KEY (serial) REFERENCES serials (serial)
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    admin_id INTEGER PRIMARY KEY,
                    username TEXT,
                    appeals_taken INTEGER DEFAULT 0,
                    is_main_admin BOOLEAN DEFAULT FALSE
                )
            """)
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS notification_channels (
                    channel_id INTEGER PRIMARY KEY,
                    channel_name TEXT,
                    topic_id INTEGER
                )
            """)
            await self.conn.commit()
        logger.info("Таблицы базы данных созданы или проверены")

    async def add_serial(self, serial):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "INSERT OR IGNORE INTO serials (serial, upload_date, status) VALUES (?, ?, ?)",
                (serial, datetime.now().isoformat(), "active")
            )
            await self.conn.commit()
            if cursor.rowcount == 0:
                logger.debug(f"Серийный номер {serial} уже существует в базе")
            else:
                logger.info(f"Серийный номер {serial} добавлен в базу")

    async def add_appeal(self, serial, username, description, media_files, user_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO appeals (serial, username, description, media_files, status, user_id, created_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (serial, username, description, json.dumps(media_files), "new", user_id, datetime.now().isoformat())
            )
            appeal_id = cursor.lastrowid
            await cursor.execute(
                "UPDATE serials SET appeal_count = appeal_count + 1 WHERE serial = ?",
                (serial,)
            )
            await self.conn.commit()
            await cursor.execute("SELECT appeal_count FROM serials WHERE serial = ?", (serial,))
            appeal_count = (await cursor.fetchone())["appeal_count"]
            logger.info(f"Заявка №{appeal_id} создана для серийника {serial} пользователем @{username} (ID: {user_id})")
            return appeal_id, appeal_count

    async def check_duplicate_appeal(self, serial, description, user_id):
        async with self.conn.cursor() as cursor:
            time_threshold = (datetime.now() - timedelta(hours=24)).isoformat()
            await cursor.execute(
                "SELECT * FROM appeals WHERE serial = ? AND description = ? AND user_id = ? AND status IN ('new', 'in_progress', 'postponed') AND created_time >= ?",
                (serial, description, user_id, time_threshold)
            )
            duplicate = await cursor.fetchone()
            if duplicate:
                logger.warning(f"Обнаружена дублирующая заявка для серийника {serial} от пользователя ID {user_id}")
            return duplicate

    async def take_appeal(self, appeal_id, admin_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "UPDATE appeals SET status = ?, admin_id = ?, taken_time = ? WHERE appeal_id = ?",
                ("in_progress", admin_id, datetime.now().isoformat(), appeal_id)
            )
            await cursor.execute(
                "UPDATE admins SET appeals_taken = appeals_taken + 1 WHERE admin_id = ?",
                (admin_id,)
            )
            await self.conn.commit()
            logger.info(f"Заявка №{appeal_id} взята в работу сотрудником ID {admin_id}")

    async def delegate_appeal(self, appeal_id, new_admin_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "UPDATE appeals SET admin_id = ? WHERE appeal_id = ?",
                (new_admin_id, appeal_id)
            )
            await self.conn.commit()
            logger.info(f"Заявка №{appeal_id} делегирована сотруднику ID {new_admin_id}")

    async def close_appeal(self, appeal_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "UPDATE appeals SET status = ?, closed_time = ? WHERE appeal_id = ?",
                ("processed", datetime.now().isoformat(), appeal_id)
            )
            await self.conn.commit()
            logger.info(f"Заявка №{appeal_id} закрыта")

    async def save_response(self, appeal_id, response):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "UPDATE appeals SET response = ? WHERE appeal_id = ?",
                (response, appeal_id)
            )
            await self.conn.commit()
            logger.debug(f"Ответ сохранён для заявки №{appeal_id}: {response}")
        logger.info(f"Ответ для заявки №{appeal_id} сохранён в базе данных")

    async def postpone_appeal(self, appeal_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "UPDATE appeals SET status = ? WHERE appeal_id = ?",
                ("postponed", appeal_id)
            )
            await self.conn.commit()
            logger.info(f"Заявка №{appeal_id} отложена")

    async def get_appeal(self, appeal_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT * FROM appeals WHERE appeal_id = ?", (appeal_id,))
            appeal = await cursor.fetchone()
            logger.debug(f"Запрос заявки №{appeal_id}, найдена: {bool(appeal)}")
            return appeal

    async def get_serial_history(self, serial):
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT appeal_count, return_status, upload_date FROM serials WHERE serial = ?", (serial,))
            serial_data = await cursor.fetchone()
            await cursor.execute("SELECT * FROM appeals WHERE serial = ? ORDER BY taken_time DESC, appeal_id DESC", (serial,))
            appeals = await cursor.fetchall()
            logger.info(f"История серийника {serial} запрошена, найдено обращений: {len(appeals)}")
            return serial_data, appeals

    async def add_admin(self, admin_id, username, is_main_admin=False):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "INSERT OR IGNORE INTO admins (admin_id, username, is_main_admin) VALUES (?, ?, ?)",
                (admin_id, username, is_main_admin)
            )
            await self.conn.commit()
            logger.info(f"Сотрудник @{username} (admin_id: {admin_id}, is_main_admin: {is_main_admin}) добавлен в базу")

    async def add_notification_channel(self, channel_id, channel_name, topic_id=None):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "INSERT OR IGNORE INTO notification_channels (channel_id, channel_name, topic_id) VALUES (?, ?, ?)",
                (channel_id, channel_name, topic_id)
            )
            await self.conn.commit()
            logger.info(f"Канал {channel_name} (ID: {channel_id}, topic_id: {topic_id}) добавлен для уведомлений")

    async def get_notification_channels(self):
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT * FROM notification_channels")
            channels = await cursor.fetchall()
            logger.debug(f"Запрошены каналы уведомлений, найдено: {len(channels)}")
            return channels

    async def get_assigned_appeals(self, admin_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT * FROM appeals WHERE admin_id = ? AND status IN ('in_progress', 'postponed')", (admin_id,))
            appeals = await cursor.fetchall()
            logger.info(f"Запрошены заявки сотрудника ID {admin_id}, найдено: {len(appeals)}")
            return appeals

    async def get_user_appeals(self, user_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute("SELECT * FROM appeals WHERE user_id = ? ORDER BY created_time DESC", (user_id,))
            appeals = await cursor.fetchall()
            logger.info(f"Запрошены заявки пользователя ID {user_id}, найдено: {len(appeals)}")
            return appeals

    async def get_open_appeals(self, admin_id):
        async with self.conn.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM appeals WHERE status IN ('new', 'postponed', 'overdue') AND (admin_id IS NULL OR admin_id != ?)",
                (admin_id,)
            )
            appeals = await cursor.fetchall()
            logger.info(f"Запрошены открытые заявки для сотрудника ID {admin_id}, найдено: {len(appeals)}")
            return appeals