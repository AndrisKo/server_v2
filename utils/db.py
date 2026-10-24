import os
import psycopg
from psycopg.rows import dict_row
from utils.logger import log_action

from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    """Подключение к базе данных PostgreSQL."""

    port = os.environ.get("POSTGRES_PORT", "5488")
    if port.isdigit():
        port = int(port)
    else:
        port = 5488
    return psycopg.connect(
        dbname=os.environ.get("POSTGRES_DB"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD"),
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=port,
        connect_timeout=3,
    )


def init_db():
    """Создаёт таблицу images, если её ещё нет."""
    query = """
    CREATE TABLE IF NOT EXISTS images (
        id SERIAL PRIMARY KEY,
        filename TEXT NOT NULL,
        original_name TEXT NOT NULL,
        size INTEGER NOT NULL,
        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        file_type TEXT NOT NULL,
        uploader_ip TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_images_upload_time ON images(upload_time DESC);
    ALTER TABLE images ADD COLUMN IF NOT EXISTS uploader_ip TEXT;
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


def save_image_metadata(filename, original_name, size, file_type, uploader_ip=None, conn=None):
    """Сохранение информации о загруженном файле в таблицу images."""
    query = """
        INSERT INTO images (filename, original_name, size, file_type, uploader_ip)
        VALUES (%s, %s, %s, %s, %s) RETURNING id;
    """
    # если подключение уже передали (для пачки картинок) — используем его
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(query, (filename, original_name, size, file_type, uploader_ip))
            result = cur.fetchone()
            if result is None:
                raise RuntimeError("Не удалось получить ID созданной записи")
            return result[0]

    # если вызов одиночный — открываем своё подключение и коммитим
    with get_db_connection() as new_conn:
        with new_conn.cursor() as cur:
            cur.execute(query, (filename, original_name, size, file_type, uploader_ip))
            result = cur.fetchone()
            if result is None:
                raise RuntimeError("Не удалось получить ID созданной записи")
            new_id = result[0]
        new_conn.commit()
    return new_id

def get_images_page(page=1, page_size=10):
    """Возвращает список картинок для страницы и общее количество."""
    # Защита от неправильного номера страницы
    page = int(page)
    if page < 1:
        page = 1

    offset = (page - 1) * page_size

    query = """
        SELECT id, filename, original_name, size,
               ROUND(size / 1024.0, 1) AS size_kb,
               TO_CHAR(upload_time, 'YYYY-MM-DD HH24:MI:SS') AS upload_time,
               file_type, uploader_ip
        FROM images
        ORDER BY id DESC
        LIMIT %s OFFSET %s
    """

    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Считаем общее количество
            cur.execute("SELECT COUNT(*) AS total FROM images;")
            row = cur.fetchone()
            if row:
                total = row["total"]
            else:
                total = 0

            # Берём нужную страницу
            cur.execute(query, (page_size, offset))
            images = cur.fetchall()

    return images, total

def delete_image_by_id(image_id, client_ip=None):
    """Удаление записи об изображении из базы данных по id (только если совпадает IP)."""
    # id должен быть числом
    try:
        image_id = int(image_id)
    except (ValueError, TypeError):
        return None

    # Если передан IP — удаляем только если совпадает IP автора
    if client_ip is not None:
        query = "DELETE FROM images WHERE id = %s AND (uploader_ip = %s OR uploader_ip IS NULL) RETURNING filename;"
        params = (image_id, client_ip)
    else:
        query = "DELETE FROM images WHERE id = %s RETURNING filename;"
        params = (image_id,)

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        conn.commit()

    # если такой записи не было (или IP чужой) - возвращаем None
    if row is None:
        return None
    return str(row[0])

def get_image_by_id(image_id):
    """Поиск информации об изображении по id."""
    # id должен быть числом
    try:
        image_id = int(image_id)
    except (ValueError, TypeError):
        return None

    query = "SELECT id, filename, original_name, size, TO_CHAR(upload_time, 'YYYY-MM-DD HH24:MI:SS') AS upload_time, file_type FROM images WHERE id = %s;"
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (image_id,))
            row = cur.fetchone()

    if row is None:
        return None
    return dict(row)
