# Модуль логирования действий приложения

import datetime
import os
from pathlib import Path
import threading

PROJECT_ROOT = Path(__file__).parent.parent.parent
# print(PROJECT_ROOT, "<>", PROJECT_ROOT.absolute())

LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_FILE = LOGS_DIR / "app.log"
LOGS_FILE.parent.mkdir(parents=True, exist_ok=True)

# print(LOGS_FILE)
# print(LOGS_DIR)
