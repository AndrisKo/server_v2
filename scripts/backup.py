import os
import subprocess
import sys
from datetime import datetime
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


def make_backup():
    """Создает SQL-дамп базы данных и архив изображений."""
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    sql_file = BACKUP_DIR / f"backup_{stamp}.sql"
    tar_file = BACKUP_DIR / f"images_{stamp}.tar.gz"

    # 1. Дамп базы данных
    dump_cmd = ["docker", "exec", DB_CONTAINER, "pg_dump", "-U", DB_USER, "--clean", "--if-exists", DB_NAME]
    with open(sql_file, "wb") as f:
        res = subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0 or sql_file.stat().st_size == 0:
        sql_file.unlink(missing_ok=True)
        log_action("Ошибка", f"сбой создания бэкапа ({res.stderr.strip() or 'пустой дамп'})")
        return False

    # 2. Архив картинок из контейнера приложения
    tar_cmd = ["docker", "exec", APP_CONTAINER, "tar", "-czf", "-", "-C", STORAGE_DIR, "."]
    with open(tar_file, "wb") as f:
        res = subprocess.run(tar_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        tar_file.unlink(missing_ok=True)
        log_action("Бэкап", f"создан {sql_file.name}, ошибка архивации картинок ({res.stderr.strip()})")
    else:
        log_action("Бэкап", f"созданы {sql_file.name} и {tar_file.name}")
    return True


if __name__ == "__main__":
    sys.exit(0 if make_backup() else 1)
