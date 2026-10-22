import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "app.log"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),  # вывод в консоль
        logging.FileHandler(LOG_FILE, encoding="utf-8"),  # запись в файл
    ],
)

def log_action(action, message=""):
    """Запись действия в системный журнал app.log"""

    line = f"{action}: {message}" if message else str(action)
    logging.info(line)


