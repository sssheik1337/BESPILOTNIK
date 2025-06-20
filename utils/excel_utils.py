import pandas as pd
import re
from io import BytesIO
from database.db import add_serial
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def validate_serial(serial):
    return bool(re.match(r'^[A-Za-z0-9]{8,20}$', str(serial)))

async def import_serials(file_io, db_pool):
    try:
        df = pd.read_excel(file_io)
        if 'Serial' not in df.columns:
            logger.error("Отсутствует столбец 'Serial' в загруженном файле")
            return None, "Файл должен содержать столбец 'Serial'."

        serials = df['Serial'].dropna().astype(str).tolist()

        result = {'added': 0, 'skipped': 0, 'invalid': []}
        existing_serials = set()

        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT serial FROM serials")
            existing_serials.update(row['serial'] for row in rows)

        for serial in serials:
            if serial in existing_serials:
                logger.info(f"Серийный номер {serial} уже существует, пропущен")
                result['skipped'] += 1
                continue
            if validate_serial(serial):
                await add_serial(serial)
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

async def export_serials(db_pool):
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.serial, s.appeal_count, s.return_status, a.username, a.created_time, a.taken_time, a.closed_time, a.new_serial
                FROM serials s
                LEFT JOIN appeals a ON s.serial = a.serial
            """)

        data = []
        for row in rows:
            username = row['username'] or 'Не назначен'
            created_time = row['created_time']
            if created_time:
                try:
                    created_time = datetime.strptime(created_time, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    created_time = created_time
            else:
                created_time = 'Нет обращений'
            taken_time = row['taken_time']
            if taken_time:
                try:
                    taken_time = datetime.strptime(taken_time, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    taken_time = taken_time
            else:
                taken_time = 'Нет обращений'
            closed_time = row['closed_time']
            if closed_time:
                try:
                    closed_time = datetime.strptime(closed_time, "%Y-%m-%dT%H:%M").strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    closed_time = closed_time
            else:
                closed_time = 'Нет обращений'
            new_serial = row['new_serial'] or 'Не указан'
            data.append({
                'Serial': row['serial'],
                'Appeal Count': row['appeal_count'],
                'Return Status': row['return_status'] or 'Не указан',
                'Admin Username': username,
                'Created Time': created_time,
                'Taken Time': taken_time,
                'Closed Time': closed_time,
                'New Serial': new_serial
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