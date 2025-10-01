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
    Возвращает словарь с состоянием принтера через lpstat и lpoptions
    """
    status = {
        "online": True,
        "paper_out": False,
        "toner_low": False,
        "door_open": False,
        "raw_status": ""
    }

    try:
        res = subprocess.run(
            ["lpstat", "-p", printer],
            capture_output=True,
            text=True,
            timeout=5
        )
        out = res.stdout.lower()
        status["raw_status"] = out.strip()

        if "disabled" in out or "unknown" in out:
            status["online"] = False
        if "out of paper" in out:
            status["paper_out"] = True
        if "toner" in out and ("low" in out or "empty" in out):
            status["toner_low"] = True
        if "door open" in out:
            status["door_open"] = True

    except Exception as e:
        status["online"] = False
        status["raw_status"] = f"error: {e}"

    return status
