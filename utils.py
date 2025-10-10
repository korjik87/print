import subprocess
import logging
import sys
import os
import re
import threading
from datetime import datetime
from typing import Dict, Any

# Эти переменные будут устанавливаться в worker/rabbit
connection = None
channel = None

try:
    import config
except ImportError:
    config = type("config", (), {"LOG_FILE": "worker.log"})  # fallback

logger: logging.Logger = None


# Глобальная переменная для хранения текущего job_id
current_job_id = None
current_job_lock = threading.Lock()

def update_current_job_id(task):
    """
    Обновляет текущий job_id из задачи RabbitMQ
    """
    global current_job_id
    with current_job_lock:
        current_job_id = task.get('job_id')

def get_current_job_id():
    """
    Возвращает текущий job_id (потокобезопасно)
    """
    global current_job_id
    with current_job_lock:
        return current_job_id


def setup_logger() -> logging.Logger:
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
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    handler_file = logging.FileHandler(log_file)
    handler_file.setFormatter(formatter)
    logger.addHandler(handler_file)

    return logger


def cleanup_file(path: str):
    """Удаление временного файла"""
    if path and os.path.exists(path) and os.path.isfile(path):
        try:
            os.remove(path)
            logger.info(f"Удален временный файл {path}")
        except Exception as e:
            logger.error(f"Не удалось удалить {path}: {e}")


def graceful_exit(signum, frame):
    """Корректное завершение работы"""
    global logger
    if not logger:
        logger = setup_logger()
    logger.info("Останавливаю worker...")
    sys.exit(0)


def get_printer_status(printer: str) -> Dict[str, Any]:
    """Базовый статус принтера через lpstat"""
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
        out = res.stdout.strip()
        status["raw_status"] = out
        out_lower = out.lower()

        if "disabled" in out_lower or "unknown" in out_lower:
            status["online"] = False
        if any(err in out_lower for err in ["out of paper", "paper jam"]):
            status["paper_out"] = True
        if "toner" in out_lower and any(t in out_lower for t in ["low", "empty"]):
            status["toner_low"] = True
        if any(door in out_lower for door in ["door open", "cover open"]):
            status["door_open"] = True

    except Exception as e:
        status["online"] = False
        status["raw_status"] = f"error: {e}"

    return status


def get_detailed_printer_status(printer: str) -> Dict[str, Any]:
    """
    Подробный статус принтера:
      - флаги состояния
      - количество заданий в очереди
      - ID текущей задачи
      - "сырое" состояние для отладки
    """
    status: Dict[str, Any] = {
        "online": True,
        "paper_out": False,
        "toner_low": False,
        "door_open": False,
        "jobs_in_queue": 0,
        "current_job_id": None,
        "raw_status": ""
    }

    commands = [
        ["lpstat", "-l", "-p", printer],
        ["lpq", "-P", printer],
        ["lpoptions", "-l", "-p", printer],
        ["lpstat", "-o"]
    ]

    all_outputs = []
    for cmd in commands:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            all_outputs.append(res.stdout)
        except Exception:
            continue

    full_output = "\n".join(all_outputs)
    status["raw_status"] = full_output

    # Для анализа приводим к нижнему регистру
    full_output_lower = full_output.lower()

    # Флаги состояния
    status_flags = {
        "online": ["disabled", "printer is not available", "Не удается получить статус принтера"],
        "paper_out": [
            "out of paper", "paper out", "paper jam",
            "media-empty-error", "media-needed-error",
            "нет бумаги", "закончилась бумага", "загрузите бумагу"
        ],
        "toner_low": ["toner low", "low toner", "toner empty", "тонер низкий", "замените тонер"],
        "door_open": ["door open", "cover open", "open cover", "дверца открыта", "крышка открыта"]
    }

    # Поиск ошибок
    for key, patterns in status_flags.items():
        for p in patterns:
            check_output = full_output if any(e in p for e in ["media-empty-error", "media-needed-error"]) else full_output_lower
            if p in check_output:
                status[key if key != "online" else "online"] = False if key == "online" else True
                break

    # Подсчет заданий в очереди
    try:
        queue_res = subprocess.run(["lpstat", "-o"], capture_output=True, text=True, timeout=5)
        printer_jobs = [line for line in queue_res.stdout.splitlines() if printer.lower() in line.lower() and line.strip()]
        status["jobs_in_queue"] = len(printer_jobs)
    except Exception:
        status["jobs_in_queue"] = 0

    status["job_id"] = get_current_job_id()

    # Определение текущей задачи (по ID)
    match = re.search(rf"{re.escape(printer)}-(\d+)", full_output, re.IGNORECASE)
    if match:
        status["current_job_id"] = match.group(1)

    # Проверка онлайн: если принтер оффлайн или есть ошибки, задачи не отправляем
    status["can_print"] = status["online"] and not (status["paper_out"] or status["toner_low"] or status["door_open"])

    return status

