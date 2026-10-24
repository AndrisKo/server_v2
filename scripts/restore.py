#!/usr/bin/env python3
"""
Скрипт восстановления базы данных PostgreSQL и файлов картинок из резервной копии.
Восстанавливает:
1. Базу данных из backups/backup_ГГГГ-ММ-ДД_ЧЧММСС.sql
2. Файлы изображений из backups/images_ГГГГ-ММ-ДД_ЧЧММСС.tar.gz (если архив существует)
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from utils.logger import log_action

load_dotenv(PROJECT_ROOT / ".env")

BACKUP_DIR = PROJECT_ROOT / "backups"
DB_CONTAINER = os.environ["DB_CONTAINER"]
APP_CONTAINER = os.environ["APP_CONTAINER"]
DB_USER = os.environ["POSTGRES_USER"]
DB_NAME = os.environ["POSTGRES_DB"]
STORAGE_DIR = os.environ.get("STORAGE_DIR", "/images")


def restore_backup(name=None):
    """Восстанавливает базу данных и архив картинок. Без аргумента берет самый свежий бэкап."""
    if name:
        sql_file = Path(name)
        if not sql_file.is_file():
            sql_file = BACKUP_DIR / sql_file.name
    else:
        files = sorted(BACKUP_DIR.glob("backup_*.sql"))
        sql_file = files[-1] if files else None

    if not sql_file or not sql_file.is_file():
        log_action("Ошибка", "файл резервной копии не найден")
        return False

    # 1. База данных
    psql_cmd = ["docker", "exec", "-i", DB_CONTAINER, "psql", "-q", "-U", DB_USER, "-d", DB_NAME, "-v", "ON_ERROR_STOP=1"]
    with open(sql_file, "rb") as f:
        res = subprocess.run(psql_cmd, stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        log_action("Ошибка", f"сбой восстановления БД ({res.stderr.strip()})")
        return False

    # 2. Картинки (если есть архив с таким же временем)
    tar_file = BACKUP_DIR / (sql_file.stem.replace("backup_", "images_") + ".tar.gz")
    if not tar_file.exists():
        log_action("Восстановление", f"восстановлена БД из {sql_file.name}")
        return True

    tar_cmd = ["docker", "exec", "-i", APP_CONTAINER, "tar", "-xzf", "-", "-C", STORAGE_DIR]
    with open(tar_file, "rb") as f:
        res = subprocess.run(tar_cmd, stdin=f, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        log_action("Восстановление", f"восстановлена БД из {sql_file.name}, ошибка картинок ({res.stderr.strip()})")
    else:
        log_action("Восстановление", f"восстановлены БД из {sql_file.name} и картинки из {tar_file.name}")
    return True


if __name__ == "__main__":
    sys.exit(0 if restore_backup(sys.argv[1] if len(sys.argv) > 1 else None) else 1)
