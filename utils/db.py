import os
import time
import psycopg
from psycopg.rows import dict_row
from utils.logger import log_action

from dotenv import load_dotenv

load_dotenv()

# Настройки подключения к PostgreSQL из переменных окружения
POSTGRES_DB = os.environ.get("POSTGRES_DB")
POSTGRES_USER = os.environ.get("POSTGRES_USER")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", 5488))


def get_db_connection():
    """Подключение к базе данных PostgreSQL."""
    return psycopg.connect(
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=POSTGRES_PORT,
        connect_timeout=3,
    )


def init_db():
    """Создаёт таблицу images, если её ещё нет."""
    query = """
            CREATE TABLE IF NOT EXISTS images
            (
                id
                SERIAL
                PRIMARY
                KEY,
                filename
                TEXT
                NOT
                NULL,
                original_name
                TEXT
                NOT
                NULL,
                size
                INTEGER
                NOT
                NULL,
                upload_time
                TIMESTAMP
                DEFAULT
                CURRENT_TIMESTAMP,
                file_type
                TEXT
                NOT
                NULL
            );
            CREATE INDEX IF NOT EXISTS idx_images_upload_time ON images(upload_time DESC); \
            """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()
        log_action("Успех", "таблица images готова")
        return True
    except Exception as e:
        log_action("Ошибка", f"сбой инициализации базы данных ({e})")
        return False


def get_stored_images(storage_dir=None):
    """Получает список всех картинок напрямую из базы данных, свежие сверху."""
    query = "SELECT filename AS name, size, TO_CHAR(upload_time, 'YYYY-MM-DD HH24:MI:SS') AS time FROM images ORDER BY id DESC;"
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query)
            return cur.fetchall()


def save_image_metadata(filename, original_name, size, file_type):
    """Сохранение информации о загруженном файле в таблицу images."""
    query = """
            INSERT INTO images (filename, original_name, size, file_type)
            VALUES (%s, %s, %s, %s) RETURNING id; \
            """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (filename, original_name, size, file_type))
            res = cur.fetchone()
            if not res:
                raise RuntimeError("Не удалось получить ID созданной записи")
            new_id = int(res[0])
        conn.commit()
        return new_id
