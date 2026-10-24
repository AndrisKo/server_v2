#!/usr/bin/env python3
"""
Скрипт восстановления базы данных PostgreSQL и файлов картинок из резервной копии.
Восстанавливает:
1. Базу данных из backups/backup_ГГГГ-ММ-ДД_ЧЧММСС.sql
2. Файлы изображений из backups/images_ГГГГ-ММ-ДД_ЧЧММСС.tar.gz (если архив существует)
"""

import os
import sys
import subprocess
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


def restore_backup(sql_file=None):
    """Восстанавливает базу данных и архив картинок."""
    if not all([DB_CONTAINER, APP_CONTAINER, DB_USER, DB_NAME]):
        log_action("Ошибка", "в .env не заданы обязательные переменные контейнеров или БД")
        return False

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Если файл не указан, берем самый свежий .sql файл по имени (backup_ГГГГ-ММ-ДД_ЧЧММСС.sql)
    if not sql_file:
        backups = sorted(BACKUP_DIR.glob("backup_*.sql"), key=lambda p: p.name, reverse=True)
        if not backups:
            log_action("Ошибка", "в папке backups/ нет файлов резервных копий")
            return False
        filepath = backups[0]
    else:
        # Корректно разрешаем путь: как абсолютный, относительный от корня или имя из backups/
        candidate = Path(sql_file)
        if candidate.is_file():
            filepath = candidate.resolve()
        elif (BACKUP_DIR / candidate).is_file():
            filepath = (BACKUP_DIR / candidate).resolve()
        elif (PROJECT_ROOT / candidate).is_file():
            filepath = (PROJECT_ROOT / candidate).resolve()
        else:
            filepath = (BACKUP_DIR / candidate).resolve()

        if not filepath.is_relative_to(BACKUP_DIR.resolve()):
            log_action("Ошибка", "попытка доступа за пределы каталога резервных копий")
            return False

    if not filepath.exists():
        log_action("Ошибка", f"файл бэкапа не найден: {filepath.name}")
        return False

    # 1. Восстановление базы данных PostgreSQL
    cmd = ["docker", "exec", "-i"]
    if DB_PASSWORD:
        cmd.extend(["-e", f"PGPASSWORD={DB_PASSWORD}"])
    cmd.extend([DB_CONTAINER, "psql", "-q", "-U", DB_USER, "-p", str(DB_PORT), "-d", DB_NAME, "-v", "ON_ERROR_STOP=1"])

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            res = subprocess.run(cmd, stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise RuntimeError(res.stderr.strip() or "ошибка psql")
    except Exception as e:
        log_action("Ошибка", f"сбой восстановления БД ({e})")
        return False

    # 2. Восстановление архива изображений .tar.gz (если он есть)
    timestamp = filepath.stem.replace("backup_", "")
    images_file = BACKUP_DIR / f"images_{timestamp}.tar.gz"

    if images_file.exists():
        tar_cmd = ["docker", "exec", "-i", APP_CONTAINER, "tar", "-xzf", "-", "-C", STORAGE_DIR]
        try:
            with open(images_file, "rb") as f:
                tar_res = subprocess.run(tar_cmd, stdin=f, stderr=subprocess.PIPE)
            if tar_res.returncode == 0:
                log_action("Восстановление", f"восстановлены БД из {filepath.name} и картинки из {images_file.name}")
            else:
                err = tar_res.stderr.decode("utf-8", errors="replace").strip() if tar_res.stderr else "ошибка распаковки"
                log_action("Восстановление", f"восстановлена БД из {filepath.name}, ошибка распаковки картинок ({err})")
        except Exception as e:
            log_action("Восстановление", f"восстановлена БД из {filepath.name}, ошибка картинок ({e})")
    else:
        log_action("Восстановление", f"восстановлена БД из {filepath.name}")

    return True


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    success = restore_backup(arg)
    sys.exit(0 if success else 1)
