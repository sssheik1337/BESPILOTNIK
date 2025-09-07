import asyncpg
from datetime import datetime, timedelta
import json
from config import DB_CONFIG
import logging
import re
logger = logging.getLogger(__name__)

pool = None

def normalize_personal_number(pn):
    return re.sub(r'[^а-яА-Я0-9]', '', pn.lower())

def get_my_appeals_menu(appeals, page, total_appeals):
    keyboard = []
    for appeal in appeals:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Заявка №{appeal['appeal_id']} ({APPEAL_STATUSES.get(appeal['status'], appeal['status'])})",
                callback_data=f"view_appeal_{appeal['appeal_id']}"
            )
        ])
    nav_buttons = []
    if total_appeals > 10:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data=f"my_appeals_page_{page-1}"))
        if (page + 1) * 10 < total_appeals:
            nav_buttons.append(InlineKeyboardButton(text="Следующая ➡️", callback_data=f"my_appeals_page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    logger.debug(f"Создана клавиатура для 'Мои заявки' с {len(appeals)} заявками на странице {page}")
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

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

async def create_tables():
    async with pool.acquire() as conn:
        await conn.execute("""
                    CREATE TABLE IF NOT EXISTS training_centers (
                        id SERIAL PRIMARY KEY,
                        code_word TEXT UNIQUE,
                        center_name TEXT,
                        chat_link TEXT
                    )
                """)
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
                new_serial TEXT,
                last_response_time TEXT,
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                serial TEXT,
                FOREIGN KEY (serial) REFERENCES serials (serial)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS defect_reports (
                report_id SERIAL PRIMARY KEY,
                serial TEXT,
                report_date TEXT,
                report_time TEXT,
                location TEXT,
                employee_id BIGINT,
                media_links TEXT,
                FOREIGN KEY (serial) REFERENCES serials (serial),
                FOREIGN KEY (employee_id) REFERENCES admins (admin_id)
            )
        """)
        await conn.execute("""
                    CREATE TABLE IF NOT EXISTS exam_records (
                        exam_id SERIAL PRIMARY KEY,
                        fio TEXT,
                        subdivision TEXT,
                        military_unit TEXT,
                        callsign TEXT,
                        specialty TEXT,
                        contact TEXT,
                        personal_number TEXT,
                        video_link TEXT,
                        photo_links TEXT,
                        training_center_id INTEGER,
                        FOREIGN KEY (training_center_id) REFERENCES training_centers(id)
                    )
                """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id BIGINT,
                chat_id BIGINT,
                sent_time TEXT,
                PRIMARY KEY (message_id, chat_id)
            )
        """)
    logger.info("Таблицы базы данных созданы или проверены")

async def get_db_pool():
    global pool
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return pool

async def add_exam_record(fio, subdivision, military_unit, callsign, specialty, contact, personal_number, training_center_id, video_link=None, photo_links=None):
    async with pool.acquire() as conn:
        normalized = normalize_personal_number(personal_number)
        logger.debug(f"Сохраняемый личный номер: {personal_number}, нормализованный: {normalized}")
        exam_id = await conn.fetchval(
            "INSERT INTO exam_records (fio, subdivision, military_unit, callsign, specialty, contact, personal_number, training_center_id, video_link, photo_links, normalized) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING exam_id",
            fio, subdivision, military_unit, callsign, specialty, contact, personal_number, training_center_id, video_link, json.dumps(photo_links) if photo_links else None, normalized
        )
        logger.info(f"Экзамен №{exam_id} добавлен для {fio} с УТЦ ID {training_center_id}")
        return exam_id

async def update_exam_record(exam_id, video_link=None, photo_links=None):
    async with pool.acquire() as conn:
        async with conn.transaction():  # Гарантируем коммит транзакции
            result = await conn.execute("""
                UPDATE exam_records 
                SET video_link = $1, photo_links = $2
                WHERE exam_id = $3
            """, video_link, json.dumps(photo_links) if photo_links else None, exam_id)
            logger.debug(f"Обновление записи экзамена ID {exam_id}: video_link={video_link}, photo_links={photo_links}, result={result}")
        logger.info(f"Запись экзамена ID {exam_id} обновлена с видео {video_link} и фото {photo_links}")

async def get_exam_records():
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT er.*, tc.center_name 
            FROM exam_records er 
            LEFT JOIN training_centers tc ON er.training_center_id = tc.id 
            ORDER BY er.exam_id DESC
        """)
        logger.info(f"Запрошены записи экзаменов, найдено: {len(records)}")
        return records

async def get_exam_records_by_personal_number(personal_number):
    async with pool.acquire() as conn:
        normalized_personal_number = normalize_personal_number(personal_number)
        logger.debug(f"Нормализованный личный номер для поиска: {normalized_personal_number}")
        # Проверяем все записи для отладки
        all_records = await conn.fetch("""
            SELECT personal_number, encode(personal_number::bytea, 'escape') AS encoded, normalized 
            FROM exam_records
        """)
        logger.debug(f"Все записи в базе: {[(r['personal_number'], r['encoded'], r['normalized']) for r in all_records]}")
        # Поиск по числовой части
        numeric_part = re.sub(r'[^0-9]', '', normalized_personal_number)
        if numeric_part:
            logger.debug(f"Поиск по числовой части: {numeric_part}")
            records = await conn.fetch("""
                SELECT er.*, tc.center_name 
                FROM exam_records er 
                LEFT JOIN training_centers tc ON er.training_center_id = tc.id 
                WHERE REGEXP_REPLACE(normalized, '[а-яА-Я]', '') = $1
            """, numeric_part)
            logger.debug(f"Поиск по числовой части {numeric_part} нашёл: {len(records)} записей")
            if records:
                return records
        # Основной поиск по нормализованному номеру
        records = await conn.fetch("""
            SELECT er.*, tc.center_name 
            FROM exam_records er 
            LEFT JOIN training_centers tc ON er.training_center_id = tc.id 
            WHERE normalized = $1
        """, normalized_personal_number)
        logger.debug(f"Основной поиск для {normalized_personal_number} нашёл: {len(records)} записей")
        logger.info(f"Запрошены записи экзаменов по личному номеру {personal_number}, найдено: {len(records)}")
        return records

async def validate_exam_record(fio, personal_number, military_unit, subdivision, specialty, contact):
    def normalize_string(s):
        if not s:
            return ""
        # Удаляем пробелы, дефисы и приводим к нижнему регистру
        return re.sub(r'\s+|-', '', s.lower())

    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT * FROM exam_records")
        for record in records:
            # Проверяем совпадение с нормализацией
            if (normalize_string(record['fio']) == normalize_string(fio) or
                normalize_string(record['personal_number']) == normalize_string(personal_number) or
                normalize_string(record['military_unit']) == normalize_string(military_unit) or
                normalize_string(record['subdivision']) == normalize_string(subdivision) or
                normalize_string(record['specialty']) == normalize_string(specialty) or
                normalize_string(record['contact']) == normalize_string(contact)):
                return record['exam_id']
        return None

async def get_training_centers():
    async with pool.acquire() as conn:
        centers = await conn.fetch("SELECT id, center_name, chat_link FROM training_centers WHERE center_name IS NOT NULL")
        logger.info(f"Запрошены УТЦ, найдено: {len(centers)}")
        return centers

async def get_code_word():
    async with pool.acquire() as conn:
        code_word = await conn.fetchval("SELECT code_word FROM training_centers WHERE code_word IS NOT NULL LIMIT 1")
        logger.debug(f"Запрошено кодовое слово: {code_word}")
        return code_word

async def set_code_word(code_word):
    async with pool.acquire() as conn:
        # Проверяем, существует ли запись с code_word
        existing = await conn.fetchrow("SELECT id FROM training_centers WHERE code_word IS NOT NULL LIMIT 1")
        if existing:
            await conn.execute("UPDATE training_centers SET code_word = $1 WHERE id = $2", code_word, existing["id"])
        else:
            await conn.execute("INSERT INTO training_centers (code_word) VALUES ($1)", code_word)
        logger.info(f"Кодовое слово установлено: {code_word}")

async def add_training_center(center_name, chat_link):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO training_centers (center_name, chat_link) VALUES ($1, $2)",
            center_name, chat_link
        )
        logger.info(f"Добавлен УТЦ: {center_name}")

async def update_training_center(center_id, chat_link):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE training_centers SET chat_link = $1 WHERE id = $2",
            chat_link, center_id
        )
        logger.info(f"Обновлена ссылка для УТЦ ID {center_id}")

async def get_serial_history(serial):
    async with pool.acquire() as conn:
        serial_data = await conn.fetchrow(
            "SELECT * FROM serials WHERE serial = $1", serial
        )
        if not serial_data:
            logger.warning(f"Серийный номер {serial} не найден в базе")
            return None, []
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE serial = $1 ORDER BY created_time DESC", serial
        )
        logger.info(f"Запрошена история серийного номера {serial}, найдено заявок: {len(appeals)}")
        return serial_data, appeals

async def close_db():
    global pool
    if pool:
        await pool.close()
        logger.info("Пул соединений к базе данных закрыт")
        pool = None

async def add_serial(serial):
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO serials (serial, upload_date, status) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                serial, datetime.now().strftime("%Y-%m-%dT%H:%M"), "active"
            )
            logger.info(f"Серийный номер {serial} добавлен")
        except Exception as e:
            logger.error(f"Ошибка при добавлении серийного номера {serial}: {e}")
            raise

async def add_appeal(serial, username, description, media_files, user_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            appeal_count = await conn.fetchval(
                "SELECT appeal_count FROM serials WHERE serial = $1", serial
            )
            appeal_count = (appeal_count or 0) + 1
            await conn.execute(
                "UPDATE serials SET appeal_count = $1 WHERE serial = $2",
                appeal_count, serial
            )
            appeal_id = await conn.fetchval(
                "INSERT INTO appeals (serial, username, description, media_files, status, user_id, created_time, last_response_time) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $7) RETURNING appeal_id",
                serial, username, description, json.dumps(media_files), "new", user_id,
                datetime.now().strftime("%Y-%m-%dT%H:%M")
            )
    logger.info(f"Заявка №{appeal_id} создана для серийника {serial}")
    return appeal_id, appeal_count



async def check_duplicate_appeal(serial, description, user_id):
    async with pool.acquire() as conn:
        appeal = await conn.fetchrow(
            "SELECT * FROM appeals WHERE serial = $1 AND description = $2 AND user_id = $3 AND status != 'processed'",
            serial, description, user_id
        )
        return bool(appeal)

async def get_user_appeals(user_id):
    async with pool.acquire() as conn:
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE user_id = $1 ORDER BY created_time DESC", user_id
        )
        logger.info(f"Запрошены заявки пользователя ID {user_id}, найдено: {len(appeals)}")
        return appeals

async def get_appeal(appeal_id):
    async with pool.acquire() as conn:
        appeal = await conn.fetchrow("SELECT * FROM appeals WHERE appeal_id = $1", appeal_id)
        logger.info(f"Запрошена заявка №{appeal_id}")
        return appeal

async def take_appeal(appeal_id, admin_id, username):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE appeals SET admin_id = $1, username = $2, status = 'in_progress', taken_time = $3 WHERE appeal_id = $4",
                admin_id, username, datetime.now().strftime("%Y-%m-%dT%H:%M"), appeal_id
            )
            await conn.execute(
                "UPDATE admins SET appeals_taken = appeals_taken + 1 WHERE admin_id = $1",
                admin_id
            )
            logger.info(f"Заявка №{appeal_id} взята в работу администратором ID {admin_id}")

async def postpone_appeal(appeal_id, new_time):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE appeals SET status = 'postponed', taken_time = $1 WHERE appeal_id = $2",
            new_time, appeal_id
        )
        logger.info(f"Заявка №{appeal_id} отложена до {new_time}")

async def save_response(appeal_id, response):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE appeals SET response = $1 WHERE appeal_id = $2",
            response, appeal_id
        )
        logger.info(f"Ответ сохранён для заявки №{appeal_id}")
        return await conn.fetchrow("SELECT user_id, admin_id FROM appeals WHERE appeal_id = $1", appeal_id)

async def close_appeal(appeal_id):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE appeals SET status = $1, closed_time = $2 WHERE appeal_id = $3",
                "processed", datetime.now().strftime("%Y-%m-%dT%H:%M"), appeal_id
            )
    logger.info(f"Заявка №{appeal_id} закрыта")



async def delegate_appeal(appeal_id, admin_id, username, current_admin_id=None):
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Проверяем, был ли текущий администратор назначен на заявку
            if current_admin_id:
                appeal = await conn.fetchrow("SELECT admin_id FROM appeals WHERE appeal_id = $1", appeal_id)
                if appeal and appeal["admin_id"] == current_admin_id:
                    await conn.execute(
                        "UPDATE admins SET appeals_taken = appeals_taken - 1 WHERE admin_id = $1 AND appeals_taken > 0",
                        current_admin_id
                    )
                    logger.info(f"Уменьшено appeals_taken для администратора ID {current_admin_id} для заявки №{appeal_id}")
            # Обновляем заявку и увеличиваем appeals_taken для нового администратора
            await conn.execute(
                "UPDATE appeals SET admin_id = $1, username = $2, status = 'in_progress', taken_time = $3 WHERE appeal_id = $4",
                admin_id, username, datetime.now().strftime("%Y-%m-%dT%H:%M"), appeal_id
            )
            await conn.execute(
                "UPDATE admins SET appeals_taken = appeals_taken + 1 WHERE admin_id = $1",
                admin_id
            )
            logger.info(f"Заявка №{appeal_id} делегирована администратору ID {admin_id}")

async def get_open_appeals(page=0, limit=10):
    offset = page * limit
    async with pool.acquire() as conn:
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE status = 'new' ORDER BY created_time DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM appeals WHERE status = 'new'"
        )
        logger.info(f"Запрошены открытые заявки со статусом 'new', найдено: {len(appeals)}, всего: {total}, страница: {page}")
        return appeals, total

async def get_assigned_appeals(admin_id, page=0, limit=10):
    offset = page * limit
    async with pool.acquire() as conn:
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE admin_id = $1 AND status != 'closed' ORDER BY created_time DESC LIMIT $2 OFFSET $3",
            admin_id, limit, offset
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM appeals WHERE admin_id = $1 AND status != 'closed'",
            admin_id
        )
        logger.info(f"Запрошены заявки администратора ID {admin_id}, найдено: {len(appeals)}, всего: {total}, страница: {page}")
        return appeals, total

async def get_admins():
    async with pool.acquire() as conn:
        admins = await conn.fetch("SELECT admin_id, username FROM admins")
        logger.info(f"Запрошены админы, найдено: {len(admins)}")
        return admins

async def add_admin(admin_id, username):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (admin_id, username, is_main_admin) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            admin_id, username, False
        )
        logger.info(f"Админ @{username} (ID: {admin_id}) добавлен")

async def add_notification_channel(channel_id, channel_name, topic_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO notification_channels (channel_id, channel_name, topic_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            channel_id, channel_name, topic_id
        )
        logger.info(f"Канал {channel_name} (ID: {channel_id}, topic_id: {topic_id}) добавлен для уведомлений")

async def get_notification_channels():
    async with pool.acquire() as conn:
        channels = await conn.fetch("SELECT * FROM notification_channels")
        logger.info(f"Запрошены каналы уведомлений, найдено: {len(channels)}")
        return channels

async def mark_defect(serial, status):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE serials SET return_status = $1 WHERE serial = $2",
            status, serial
        )
        logger.info(f"Серийный номер {serial} отмечен как {status}")

async def start_replacement(appeal_id, old_serial, status="replacement_process"):
    async with pool.acquire() as conn:
        async with conn.transaction():
            current_status = await conn.fetchval(
                "SELECT status FROM appeals WHERE appeal_id = $1", appeal_id
            )
            if current_status == "replacement_process":
                logger.warning(f"Заявка №{appeal_id} уже в статусе 'процесс замены'")
                raise ValueError("Заявка уже в процессе замены")
            await conn.execute(
                "UPDATE appeals SET status = $1 WHERE appeal_id = $2",
                status, appeal_id
            )
            await conn.execute(
                "UPDATE serials SET return_status = 'Возврат' WHERE serial = $1",
                old_serial
            )
            logger.info(f"Заявка №{appeal_id} переведена в статус 'процесс замены' для серийника {old_serial}")

async def complete_replacement(appeal_id, new_serial, response=None):
    async with pool.acquire() as conn:
        async with conn.transaction():
            serial_exists = await conn.fetchrow(
                "SELECT serial FROM serials WHERE serial = $1", new_serial
            )
            if not serial_exists:
                logger.error(f"Новый серийный номер {new_serial} не найден в базе")
                raise ValueError(f"Новый серийный номер {new_serial} не найден в базе")
            await conn.execute(
                "UPDATE appeals SET new_serial = $1, status = $2, response = $3, closed_time = $4 WHERE appeal_id = $5",
                new_serial, "processed", response, datetime.now().strftime("%Y-%m-%dT%H:%M"), appeal_id
            )
            logger.info(f"Замена завершена для заявки №{appeal_id}, новый серийник: {new_serial}, ответ: {response}")

async def get_replacement_appeals(serial=None):
    async with pool.acquire() as conn:
        if serial:
            appeals = await conn.fetch(
                "SELECT * FROM appeals WHERE status IN ('new', 'in_progress', 'postponed', 'overdue') AND serial = $1",
                serial
            )
        else:
            appeals = await conn.fetch(
                "SELECT * FROM appeals WHERE status IN ('new', 'in_progress', 'postponed', 'overdue')"
            )
        logger.info(f"Запрошены заявки для замены (серийник: {serial or 'все'}), найдено: {len(appeals)}")
        return appeals

async def get_closed_appeals(page=0, limit=10):
    offset = page * limit
    async with pool.acquire() as conn:
        appeals = await conn.fetch(
            "SELECT * FROM appeals WHERE status = 'closed' ORDER BY closed_time DESC LIMIT $1 OFFSET $2",
            limit, offset
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM appeals WHERE status = 'closed'")
        logger.info(f"Запрошены закрытые заявки, найдено: {len(appeals)}, всего: {total}, страница: {page}")
        return appeals, total

async def add_defect_report(serial, report_date, report_time, location, media_links, employee_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO defect_reports (serial, report_date, report_time, location, media_links, employee_id) VALUES ($1, $2, $3, $4, $5, $6)",
            serial, report_date, report_time, location, media_links, employee_id
        )
        logger.info(f"Отчёт о дефекте для серийника {serial} добавлен")

async def get_defect_reports(serial=None, serial_from=None, serial_to=None):
    async with pool.acquire() as conn:
        if serial:
            reports = await conn.fetch(
                "SELECT * FROM defect_reports WHERE serial = $1", serial
            )
        elif serial_from and serial_to:
            reports = await conn.fetch(
                "SELECT * FROM defect_reports WHERE serial BETWEEN $1 AND $2 ORDER BY serial",
                serial_from, serial_to
            )
        else:
            reports = await conn.fetch("SELECT * FROM defect_reports ORDER BY report_date DESC")
        logger.info(f"Запрошены отчёты о неисправности, найдено: {len(reports)}")
        return reports