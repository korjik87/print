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
        "paused": False,  # Добавлен статус паузы
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
        if "paused" in out_lower:
            status["paused"] = True
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

def get_detailed_printer_status(printer_name: str) -> dict:
    """
    Получает детальный статус принтера через несколько команд CUPS
    """
    default_status = {
        "online": False,
        "raw_status": "Принтер недоступен",
        "can_print": False,
        "paused": False,
        "paper_out": False,
        "door_open": False,
        "toner_low": False,
        "jobs_in_queue": 0,
        "current_job_id": None,
        "errors": ["Принтер недоступен"]
    }

    try:
        # Команды для сбора информации о принтере
        commands = [
            ["lpstat", "-l", "-p", printer_name],  # Подробный статус
            ["lpstat", "-p", printer_name],  # Основной статус
            ["lpoptions", "-l", "-p", printer_name],  # Опции принтера
            ["lpstat", "-o"]  # Очередь заданий
        ]

        results = {}

        # Выполняем все команды с таймаутом
        for cmd in commands:
            try:
                if cmd[0] == "lpq":
                    # Проверяем наличие lpq в системе
                    check_lpq = subprocess.run(["which", "lpq"],
                                             capture_output=True,
                                             text=True)
                    if check_lpq.returncode != 0:
                        logger.warning("Команда lpq не найдена, пропускаем")
                        continue

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                results[" ".join(cmd)] = {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                }
            except subprocess.TimeoutExpired:
                logger.warning(f"Таймаут команды: {' '.join(cmd)}")
                results[" ".join(cmd)] = {
                    "stdout": "",
                    "stderr": "Timeout",
                    "returncode": -1
                }
            except Exception as e:
                logger.warning(f"Ошибка выполнения команды {' '.join(cmd)}: {e}")
                results[" ".join(cmd)] = {
                    "stdout": "",
                    "stderr": str(e),
                    "returncode": -1
                }

        # Проверяем основную команду lpstat -p (без -l)
        lpstat_key = "lpstat -p " + printer_name
        if lpstat_key not in results or results[lpstat_key]["returncode"] != 0:
            logger.error(f"Принтер {printer_name} не найден в CUPS")
            return default_status

        # Анализируем вывод команды lpstat -p (короткий вывод)
        lpstat_output = results[lpstat_key]["stdout"]
        lpstat_detailed_output = results.get("lpstat -l -p " + printer_name, {}).get("stdout", "")
        lpstat_o_output = results.get("lpstat -o", {}).get("stdout", "")

        # Определяем основной статус из короткого вывода
        status_text = lpstat_output.lower()
        detailed_text = lpstat_detailed_output.lower()

        # Более точное определение онлайн статуса для русской локали
        # В русской локали "свободен. Включен" означает принтер включен и готов
        # "disabled" в русской локали может быть "выключен" или "отключен"

        # Определяем включен ли принтер
        enabled_phrases = ["enabled", "включен"]
        disabled_phrases = ["disabled", "выключен", "отключен"]

        is_enabled = any(phrase in status_text for phrase in enabled_phrases)
        is_disabled = any(phrase in status_text for phrase in disabled_phrases)

        # Если нашли "выключен", то принтер точно не включен
        if is_disabled:
            is_enabled = False

        # Определяем состояние принтера
        idle_phrases = ["idle", "свободен", "готов", "ожидание"]
        printing_phrases = ["printing", "печатает", "processing", "обработка"]
        paused_phrases = ["paused", "остановлен", "приостановлен", "на паузе"]

        is_idle = any(phrase in status_text for phrase in idle_phrases)
        is_printing = any(phrase in status_text for phrase in printing_phrases)
        is_paused = any(phrase in status_text for phrase in paused_phrases)

        # Принтер онлайн если он включен и не выключен
        is_online = is_enabled and not is_disabled

        # Принтер может печатать если он включен и не на паузе
        can_print = is_enabled and not is_paused and not is_printing

        # Определяем специфические состояния из подробного вывода
        paper_phrases = ["out of paper", "paper out", "media empty", "нет бумаги", "закончилась бумага"]
        door_phrases = ["door open", "cover open", "открыта крышка", "дверь открыта"]
        toner_phrases = ["toner low", "low toner", "toner empty", "тонер низкий", "замените тонер",
                        "toner near end", "чернила на исходе", "мало тонера"]

        # Используем подробный вывод для этих проверок
        paper_out = any(phrase in detailed_text for phrase in paper_phrases)
        door_open = any(phrase in detailed_text for phrase in door_phrases)
        toner_low = any(phrase in detailed_text for phrase in toner_phrases)

        # Проверяем очередь заданий
        jobs_count = 0
        current_job_id = None

        # Используем lpstat -o для проверки очереди
        if lpstat_o_output:
            for line in lpstat_o_output.splitlines():
                if printer_name in line:
                    jobs_count += 1
                    if not current_job_id:
                        match = re.search(rf'{printer_name}-(\d+)', line)
                        if match:
                            current_job_id = match.group(1)

        # Собираем ошибки
        errors = []
        if not is_online:
            if is_disabled:
                errors.append("Принтер выключен")
            else:
                errors.append("Принтер не в сети")
        if is_paused:
            errors.append("Принтер на паузе")
        if paper_out:
            errors.append("Нет бумаги")
        if door_open:
            errors.append("Открыта крышка")
        if toner_low:
            errors.append("Мало тонера")
        if is_printing and jobs_count > 0:
            errors.append(f"Печатает задание {current_job_id}")

        # Формируем сырой статус
        raw_status = lpstat_output.strip()
        if not raw_status:
            raw_status = "Статус: получен"

        return {
            "online": is_online,
            "raw_status": raw_status,
            "can_print": can_print,
            "paused": is_paused,
            "paper_out": paper_out,
            "door_open": door_open,
            "toner_low": toner_low,
            "jobs_in_queue": jobs_count,
            "current_job_id": current_job_id,
            "errors": errors,
            "debug": {
                "is_enabled": is_enabled,
                "is_disabled": is_disabled,
                "is_idle": is_idle,
                "is_printing": is_printing,
                "commands_executed": list(results.keys())
            }
        }

    except subprocess.TimeoutExpired:
        logger.error(f"Таймаут при получении статуса принтера {printer_name}")
        default_status["errors"] = ["Таймаут получения статуса"]
        return default_status
    except Exception as e:
        logger.error(f"Ошибка получения статуса принтера {printer_name}: {e}")
        default_status["errors"] = [f"Ошибка: {str(e)}"]
        return default_status
