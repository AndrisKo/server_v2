import os
import shutil
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
IMAGES_DIR = PROJECT_ROOT / "images"
DB_CONTAINER = os.environ["DB_CONTAINER"]
DB_USER = os.environ["POSTGRES_USER"]
DB_NAME = os.environ["POSTGRES_DB"]


def make_backup():
    """Создает SQL-дамп базы данных и архив папки изображений."""
    BACKUP_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    sql_file = BACKUP_DIR / f"backup_{stamp}.sql"
    archive_base = BACKUP_DIR / f"images_{stamp}"

    # 1. Дамп базы данных из контейнера
    dump_cmd = ["docker", "exec", DB_CONTAINER, "pg_dump", "-U", DB_USER, "--clean", "--if-exists", DB_NAME]
    with open(sql_file, "w", encoding="utf-8") as f:
        res = subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE, text=True)

    if res.returncode != 0 or sql_file.stat().st_size == 0:
        sql_file.unlink(missing_ok=True)
        log_action("Ошибка", f"сбой создания бэкапа ({res.stderr.strip() or 'пустой дамп'})")
        return False

    # 2. Архив папки с картинками напрямую на сервере
    try:
        archive_path = shutil.make_archive(str(archive_base), "gztar", root_dir=IMAGES_DIR)
        tar_name = Path(archive_path).name
        log_action("Бэкап", f"созданы {sql_file.name} и {tar_name}")
    except Exception as e:
        log_action("Бэкап", f"создан {sql_file.name}, ошибка архивации картинок ({e})")

    return True


if __name__ == "__main__":
    if make_backup():
        sys.exit(0)
    else:
        sys.exit(1)
