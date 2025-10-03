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
        print (out)
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


def get_detailed_printer_status(printer: str) -> dict:
    """
    Комбинированный подход для получения максимальной информации о статусе принтера
    """
    status = {
        "online": True,
        "paper_out": False,
        "toner_low": False,
        "door_open": False,
        "jobs_in_queue": 0,
        "current_job_id": None,
        "raw_status": ""
    }

    all_outputs = []

    commands = [
        ["lpstat", "-p", printer, "-l"],
        ["lpq", "-P", printer],
        ["lpoptions", "-p", printer, "-l"],
        ["lpstat", "-o", printer]  # Добавляем для подсчета задач
    ]

    for cmd in commands:
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            all_outputs.append(res.stdout)
        except:
            continue

    full_output = "\n".join(all_outputs).lower()
    status["raw_status"] = full_output

    # Анализ комбинированного вывода
    if "disabled" in full_output or "printer is not available" in full_output:
        status["online"] = False

    # Обновленные статус-флаги с учетом CUPS ошибок
    status_flags = {
        "paper_out": [
            "out of paper",
            "paper out",
            "paper jam",
            "media-empty-error",  # CUPS ошибка пустого лотка
            "media-needed-error"  # CUPS ошибка необходимости бумаги
        ],
        "toner_low": ["toner low", "low toner", "toner empty"],
        "door_open": ["door open", "cover open", "open cover"]
    }

    for status_key, patterns in status_flags.items():
        for pattern in patterns:
            if pattern in full_output:
                status[status_key] = True
                break

    # Определение текущего задания
    if "сейчас печатает" in full_output or "printing" in full_output:
        # Ищем ID текущего задания
        import re
        job_match = re.search(rf"{re.escape(printer)}-(\d+)", full_output)
        if job_match:
            status["current_job_id"] = job_match.group(1)

    # Подсчет задач в очереди
    try:
        # Используем lpstat -o для точного подсчета
        queue_cmd = ["lpstat", "-o", printer]
        queue_result = subprocess.run(
            queue_cmd,
            capture_output=True,
            text=True,
            timeout=5
        )

        if queue_result.returncode == 0:
            # Каждая строка = одно задание в очереди
            jobs = [line for line in queue_result.stdout.split('\n') if line.strip()]
            status["jobs_in_queue"] = len(jobs)

    except Exception as e:
        # Резервный метод через lpq
        try:
            lpq_cmd = ["lpq", "-P", printer]
            lpq_result = subprocess.run(
                lpq_cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            if lpq_result.returncode == 0:
                # Парсим вывод lpq для подсчета заданий
                lines = lpq_result.stdout.split('\n')
                # Ищем строки с номерами заданий (пропускаем заголовки)
                job_lines = [line for line in lines if line.strip() and line.split()[0].isdigit()]
                status["jobs_in_queue"] = len(job_lines)
        except:
            status["jobs_in_queue"] = 0

    # Дополнительная проверка статусов CUPS
    cups_status_flags = [
        "cups-waiting-for-job-completed",  # Ожидание завершения задания
        "media-empty-error",               # Ошибка пустой бумаги
        "media-needed-error"               # Ошибка необходимости бумаги
    ]

    for flag in cups_status_flags:
        if flag in full_output:
            if flag in ["media-empty-error", "media-needed-error"]:
                status["paper_out"] = True

    return status

