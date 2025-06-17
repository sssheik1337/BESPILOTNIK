import pandas as pd
import re
from io import BytesIO
from database.models import Database
import logging

logger = logging.getLogger(__name__)

def validate_serial(serial):
    return bool(re.match(r'^[A-Za-z0-9]{8,20}$', str(serial)))

async def import_serials(file_io):
    try:
        df = pd.read_excel(file_io)
        if 'Serial' not in df.columns:
            logger.error("Отсутствует столбец 'Serial' в загруженном файле")
            return None, "Файл должен содержать столбец 'Serial'."

        serials = df['Serial'].dropna().astype(str).tolist()
        db = Database()
        await db.connect()

        result = {'added': 0, 'skipped': 0, 'invalid': []}
        existing_serials = set()

        async with db.conn.cursor() as cursor:
            await cursor.execute("SELECT serial FROM serials")
            rows = await cursor.fetchall()
            existing_serials.update(row['serial'] for row in rows)

        for serial in serials:
            if serial in existing_serials:
                logger.info(f"Серийный номер {serial} уже существует, пропущен")
                result['skipped'] += 1
                continue
            if validate_serial(serial):
                await db.add_serial(serial)
                logger.info(f"Добавлен серийный номер {serial}")
                result['added'] += 1
                existing_serials.add(serial)
            else:
                logger.warning(f"Невалидный серийный номер {serial}")
                result['invalid'].append(serial)

        logger.info(
            f"Импорт завершён: добавлено {result['added']}, пропущено {result['skipped']}, невалидных {len(result['invalid'])}")
        return result, None
    except Exception as e:
        logger.error(f"Ошибка при импорте серийных номеров: {str(e)}")
        return None, f"Ошибка при обработке файла: {str(e)}"

async def export_serials():
    try:
        db = Database()
        await db.connect()
        async with db.conn.cursor() as cursor:
            await cursor.execute("""
                SELECT s.serial, s.appeal_count, s.return_status, a.username, a.created_time, a.taken_time, a.closed_time
                FROM serials s
                LEFT JOIN appeals a ON s.serial = a.serial
            """)
            rows = await cursor.fetchall()

        data = []
        for row in rows:
            username = row['username'] or 'Не назначен'
            created_time = row['created_time'] or 'Нет обращений'
            taken_time = row['taken_time'] or 'Нет обращений'
            closed_time = row['closed_time'] or 'Нет обращений'
            data.append({
                'Serial': row['serial'],
                'Appeal Count': row['appeal_count'],
                'Return Status': row['return_status'] or 'Не указан',
                'Admin Username': username,
                'Created Time': created_time,
                'Taken Time': taken_time,
                'Closed Time': closed_time
            })
            logger.info(f"Экспортирован серийный номер {row['serial']}")

        if not data:
            logger.warning("Нет данных для экспорта")
            return None

        df = pd.DataFrame(data)
        output = BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)
        logger.info("Файл экспорта успешно создан")
        return output
    except Exception as e:
        logger.error(f"Ошибка при экспорте серийных номеров: {str(e)}")
        return None