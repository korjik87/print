import subprocess
import logging
import sys
import os
import signal
from datetime import datetime

# Эти переменные будут устанавливаться в worker/rabbit
connection = None
channel = None

from . import config

logger = None

def cleanup_file(path: str):
    """Удаление временного файла"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            print(f"Не удалось удалить {path}: {e}", file=sys.stderr)



def setup_logger():
    """Инициализация логгера"""
    global logger
    if logger:
        return logger

    logger = logging.getLogger("print_worker")
    logger.setLevel(logging.INFO)

    # формат логов
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # вывод в stdout
    handler_stdout = logging.StreamHandler(sys.stdout)
    handler_stdout.setFormatter(formatter)
    logger.addHandler(handler_stdout)

    # вывод в файл
    log_file = getattr(config, "LOG_FILE", "worker.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    handler_file = logging.FileHandler(log_file)
    handler_file.setFormatter(formatter)
    logger.addHandler(handler_file)

    return logger


def graceful_exit(signum, frame):
    """Корректное завершение работы"""
    global logger
    if not logger:
        logger = setup_logger()

    logger.info("Останавливаю worker...")
    sys.exit(0)


def get_printer_status(printer: str) -> dict:
    """
    Проверяем состояние принтера через lpstat.
    Возвращает словарь с флагами и исходным текстом.
    """
    try:
        result = subprocess.run(
            ["lpstat", "-p", printer, "-l"],
            capture_output=True,
            text=True
        )
        output = result.stdout.lower()

        status = {
            "online": "disabled" not in output and "offline" not in output,
            "paper_out": "paper-out" in output or "media-empty" in output,
            "toner_low": "toner-low" in output or "marker-supply-low" in output,
            "door_open": "door-open" in output or "cover-open" in output,
            "raw": output.strip()
        }
        return status
    except Exception as e:
        return {
            "online": False,
            "error": str(e),
            "raw": ""
        }
