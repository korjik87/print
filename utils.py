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
        ["lpstat", "-p", "-l", printer],
        ["lpq", "-P", printer],
        ["lpoptions", "-p", "-l",printer],
        ["lpstat", "-o"]  # Все задания в очереди
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

    full_output = "\n".join(all_outputs)
    status["raw_status"] = full_output

    # Для анализа приводим к нижнему регистру
    full_output_lower = full_output.lower()

    print(full_output_lower)

    # Анализ комбинированного вывода
    if "disabled" in full_output_lower or "printer is not available" in full_output_lower:
        status["online"] = False

    # Обновленные статус-флаги с учетом CUPS ошибок
    status_flags = {
        "paper_out": [
            "out of paper",
            "paper out",
            "paper jam",
            "media-empty-error",        # CUPS ошибка пустого лотка
            "media-needed-error",       # CUPS ошибка необходимости бумаги
            "cups-waiting-for-job-completed media-empty-error media-needed-error",  # Полная строка из lpstat
            "нет бумаги",               # Русский вариант
            "закончилась бумага",       # Русский вариант
            "загрузите бумагу"          # Русский вариант
        ],
        "toner_low": [
            "toner low",
            "low toner",
            "toner empty",
            "заканчивается тонер",      # Русский вариант
            "тонер низкий",             # Русский вариант
            "замените тонер"            # Русский вариант
        ],
        "door_open": [
            "door open",
            "cover open",
            "open cover",
            "откройте дверцу",          # Русский вариант
            "дверца открыта",           # Русский вариант
            "крышка открыта"            # Русский вариант
        ]
    }

    # ОСНОВНОЕ ИСПРАВЛЕНИЕ: Поиск в оригинальном выводе БЕЗ приведения к нижнему регистру
    # для CUPS ошибок, которые всегда на английском
    for status_key, patterns in status_flags.items():
        for pattern in patterns:
            # Для английских ошибок ищем в оригинальном выводе
            if any(eng_keyword in pattern for eng_keyword in ['media-empty-error', 'media-needed-error', 'cups-waiting']):
                if pattern in full_output:  # Ищем в оригинальном выводе
                    status[status_key] = True
                    break
            else:
                # Для остальных ищем в нижнем регистре
                if pattern in full_output_lower:
                    status[status_key] = True
                    break

    # Определение текущего задания (работает с русским выводом)
    if "сейчас печатает" in full_output_lower:
        # Ищем ID текущего задания в русском выводе
        job_match = re.search(rf"{re.escape(printer)}-(\d+)", full_output, re.IGNORECASE)
        if job_match:
            status["current_job_id"] = job_match.group(1)

    # Подсчет задач в очереди для конкретного принтера
    try:
        # Используем lpstat -o и фильтруем по имени принтера
        queue_cmd = ["lpstat", "-o"]
        queue_result = subprocess.run(
            queue_cmd,
            capture_output=True,
            text=True,
            timeout=5
        )

        if queue_result.returncode == 0:
            # Фильтруем строки, относящиеся к нашему принтеру
            printer_jobs = [line for line in queue_result.stdout.split('\n')
                          if printer.lower() in line.lower() and line.strip()]
            status["jobs_in_queue"] = len(printer_jobs)

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

    # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Явный поиск CUPS ошибок в оригинальном выводе
    cups_paper_errors = [
        "media-empty-error",
        "media-needed-error"
    ]

    for error in cups_paper_errors:
        if error in full_output:  # Ищем в оригинальном выводе
            status["paper_out"] = True
            break

    return status

