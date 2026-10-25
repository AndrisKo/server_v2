import os
import shutil
import subprocess
import sys
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


def restore_backup(name=None):
    """Восстанавливает базу данных и архив картинок. Без аргумента берет самый свежий бэкап."""
    if name:
        sql_file = Path(name)
        if not sql_file.is_file():
            sql_file = BACKUP_DIR / sql_file.name
    else:
        files = sorted(BACKUP_DIR.glob("backup_*.sql"))
        if files:
            sql_file = files[-1]
        else:
            sql_file = None

    if not sql_file or not sql_file.is_file():
        log_action("Ошибка", "файл резервной копии не найден")
        return False

    # 1. Восстановление базы данных
    psql_cmd = ["docker", "exec", "-i", DB_CONTAINER, "psql", "-q", "-U", DB_USER, "-d", DB_NAME, "-v", "ON_ERROR_STOP=1"]
    with open(sql_file, "r", encoding="utf-8") as f:
        res = subprocess.run(psql_cmd, stdin=f, capture_output=True, text=True)

    if res.returncode != 0:
        log_action("Ошибка", f"сбой восстановления БД ({res.stderr.strip()})")
        return False

    # 2. Восстановление картинок в папку ./images на сервере
    tar_name = sql_file.name.replace("backup_", "images_").replace(".sql", ".tar.gz")
    tar_file = BACKUP_DIR / tar_name

    if not tar_file.exists():
        log_action("Восстановление", f"восстановлена БД из {sql_file.name}")
        return True

    try:
        IMAGES_DIR.mkdir(exist_ok=True)
        shutil.unpack_archive(str(tar_file), extract_dir=IMAGES_DIR)
        log_action("Восстановление", f"восстановлены БД из {sql_file.name} и картинки из {tar_file.name}")
    except Exception as e:
        log_action("Восстановление", f"восстановлена БД из {sql_file.name}, ошибка картинок ({e})")

    return True


if __name__ == "__main__":
    backup_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if restore_backup(backup_arg):
        sys.exit(0)
    else:
        sys.exit(1)
