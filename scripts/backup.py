#!/usr/bin/env python3
"""
Скрипт резервного копирования базы данных PostgreSQL и файлов картинок.
Создает:
1. Дамп базы данных: backups/backup_ГГГГ-ММ-ДД_ЧЧММСС.sql
2. Архив файлов картинок: backups/images_ГГГГ-ММ-ДД_ЧЧММСС.tar.gz
"""

import os
import subprocess
from datetime import datetime
import sys
from pathlib import Path

# Папки проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.logger import log_action
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

BACKUP_DIR = PROJECT_ROOT / "backups"

# Настройки контейнеров
DB_CONTAINER = os.environ.get("DB_CONTAINER", "")
APP_CONTAINER = os.environ.get("APP_CONTAINER", "")
DB_USER = os.environ.get("POSTGRES_USER", "")
DB_NAME = os.environ.get("POSTGRES_DB", "")
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
DB_PORT = os.environ.get("POSTGRES_PORT", "5488")
STORAGE_DIR = os.environ.get("STORAGE_DIR", "/images")


def make_backup():
    """Создает SQL-дамп базы данных и архив изображений."""
    if not all([DB_CONTAINER, APP_CONTAINER, DB_USER, DB_NAME]):
        log_action("Ошибка", "в .env не заданы обязательные переменные контейнеров или БД")
        return False

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # 1. Дамп базы данных PostgreSQL
    sql_filename = f"backup_{timestamp}.sql"
    sql_filepath = BACKUP_DIR / sql_filename

    cmd_sql = ["docker", "exec"]
    if DB_PASSWORD:
        cmd_sql.extend(["-e", f"PGPASSWORD={DB_PASSWORD}"])
    cmd_sql.extend([DB_CONTAINER, "pg_dump", "-U", DB_USER, "-p", str(DB_PORT), "--clean", "--if-exists", DB_NAME])

    try:
        with open(sql_filepath, "w", encoding="utf-8") as f:
            res = subprocess.run(cmd_sql, stdout=f, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise RuntimeError(res.stderr.strip() or "ошибка pg_dump")

        sql_size = sql_filepath.stat().st_size
        if sql_size == 0:
            raise RuntimeError(f"{sql_filename} пуст")
    except Exception as e:
        sql_filepath.unlink(missing_ok=True)
        log_action("Ошибка", f"сбой создания бэкапа ({e})")
        return False

    # 2. Архивирование файлов изображений из контейнера
    images_filename = f"images_{timestamp}.tar.gz"
    images_filepath = BACKUP_DIR / images_filename

    tar_cmd = ["docker", "exec", APP_CONTAINER, "tar", "-czf", "-", "-C", STORAGE_DIR, "."]
    try:
        with open(images_filepath, "wb") as f:
            tar_res = subprocess.run(tar_cmd, stdout=f, stderr=subprocess.PIPE)

        if tar_res.returncode == 0 and images_filepath.exists() and images_filepath.stat().st_size > 0:
            img_size = images_filepath.stat().st_size
            log_action("Бэкап", f"созданы {sql_filename} ({sql_size} байт) и {images_filename} ({img_size} байт)")
        else:
            images_filepath.unlink(missing_ok=True)
            log_action("Бэкап", f"создан {sql_filename} ({sql_size} байт)")
    except Exception as e:
        images_filepath.unlink(missing_ok=True)
        log_action("Бэкап", f"создан {sql_filename} ({sql_size} байт), ошибка архивации картинок: {e}")

    return True


if __name__ == "__main__":
    success = make_backup()
    sys.exit(0 if success else 1)
