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

logger = logging.getLogger(__name__)


def log_action(action, message=""):
    """Запись действия в системный журнал app.log и вывод в терминал."""

    line = f"{action}: {message}" if message else str(action)
    logger.info(line)


if __name__ == "__main__":
    log_action("Тест", "Логер работает отлично!")
    log_action("Перезагрузка")