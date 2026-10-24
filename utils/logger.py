import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "app.log"

handlers: list[logging.Handler] = [logging.StreamHandler()]

try:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
except (PermissionError, OSError):
    pass

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=handlers,
)

def log_action(action, message=""):
    """Запись действия в системный журнал app.log"""

    line = f"{action}: {message}" if message else str(action)
    logging.info(line)


