import os
import psycopg
from psycopg.rows import dict_row
from utils.logger import log_action

from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    """Подключение к базе данных PostgreSQL."""
    return psycopg.connect(
        dbname=os.environ.get("POSTGRES_DB"),
        user=os.environ.get("POSTGRES_USER"),
        password=os.environ.get("POSTGRES_PASSWORD"),
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5488)),
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


def save_image_metadata(filename, original_name, size, file_type, uploader_ip):
    """Сохранение информации о загруженном файле в таблицу images."""
    query = """
        INSERT INTO images (filename, original_name, size, file_type, uploader_ip)
        VALUES (%s, %s, %s, %s, %s);
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (filename, original_name, size, file_type, uploader_ip))
        conn.commit()


def get_images_page(page=1, page_size=10):
    """Возвращает список картинок для страницы и общее количество."""
    offset = (page - 1) * page_size

    query = """
        SELECT id, filename, filename AS name, original_name, size,
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
            total = cur.fetchone()["total"]

            # Берём нужную страницу
            cur.execute(query, (page_size, offset))
            images = cur.fetchall()

    return images, total


def delete_image_by_id(image_id, client_ip):
    """Удаление записи об изображении по id (только если совпадает IP автора). Возвращает имя файла."""
    query = "DELETE FROM images WHERE id = %s AND (uploader_ip = %s OR uploader_ip IS NULL) RETURNING filename;"

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (image_id, client_ip))
            row = cur.fetchone()
        conn.commit()

    # если такой записи не было (или IP чужой) - возвращаем None
    if row is None:
        return None
    return str(row[0])


def update_image_size(filename: str, new_size: int):
    """Обновляет размер файла в БД после завершения фоновой оптимизации."""
    query = "UPDATE images SET size = %s WHERE filename = %s;"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (new_size, filename))
        conn.commit()

