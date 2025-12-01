import subprocess
import tempfile
import os
import base64
import uuid
import time
import shutil
import re
import traceback

from . import config
from .utils import cleanup_file, get_detailed_printer_status, setup_logger, update_current_job_id
from .restart_cups import restart_cups_service

logger = setup_logger()

def printer_exists(printer_name: str, try_recovery: bool = True, logger=None) -> bool:
    """
    Проверяет существование принтера с безопасным восстановлением

    Args:
        printer_name: имя принтера
        try_recovery: пытаться ли восстановить принтер
        logger: логгер для сообщений

    Returns:
        bool: True если принтер существует
    """
    log = logger or print

    # Базовая проверка
    try:
        result = subprocess.run(
            ["lpstat", "-p", printer_name],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            # Проверяем, что принтер действительно в списке
            output = result.stdout.lower()
            if printer_name.lower() in output and "unknown" not in output:
                return True

        # Принтер не найден
        if not try_recovery:
            return False

        log(f"⚠️ Принтер '{printer_name}' не найден, пытаемся восстановить...")

        # 1. Простая проверка через несколько секунд (может быть временная проблема)
        time.sleep(2)
        result = subprocess.run(
            ["lpstat", "-p", printer_name],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            log(f"✅ Принтер '{printer_name}' восстановился сам")
            return True

        # 2. Пробуем безопасный перезапуск служб
        log("🔄 Пробуем безопасный перезапуск служб...")
        restart_cups_service(log, force=False)

        # Даем время на восстановление
        time.sleep(10)

        # 3. Финальная проверка
        result = subprocess.run(
            ["lpstat", "-p", printer_name],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            log(f"✅ Принтер '{printer_name}' восстановлен после перезапуска служб")
            return True
        else:
            log(f"❌ Принтер '{printer_name}' все еще не найден после восстановления")
            return False

    except Exception as e:
        log(f"❌ Ошибка при проверке принтера '{printer_name}': {e}")
        return False

def get_available_printers():
    """Получает список всех доступных принтеров"""
    try:
        result = subprocess.run(
            ["lpstat", "-a"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            printers = []
            for line in result.stdout.splitlines():
                if line.strip():
                    printer_name = line.split()[0]
                    printers.append(printer_name)
            return printers
        return []
    except Exception as e:
        logger.error(f"Ошибка при получении списка принтеров: {e}")
        return []

def print_raw(printer: str, tmp_path: str):
    cmd = ["nc", "-w1", printer, "9100"]
    with open(tmp_path, "rb") as f:
        result = subprocess.run(cmd, input=f.read(), capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="ignore").strip()
        cli = f"nc -w1 {printer} < {tmp_path}"
        raise Exception(f"Ошибка RAW-печати: {stderr}, cmd: {cli}")

def wait_for_print_completion(printer_name: str, expected_job_id: str, timeout: int = 180):
    """
    Ожидает завершения задания печати по job_id
    """
    logger.info(f"⏳ Ожидаем завершения печати задания {expected_job_id}...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            # Получаем статус принтера
            status = get_detailed_printer_status(printer_name)

            # Если задание завершено и исчезло из очереди
            if status["jobs_in_queue"] == 0:
                logger.info(f"✅ Задание {expected_job_id} завершено")
                return True

            # Если задание все еще в очереди
            current_job_id = status.get("current_job_id")
            if current_job_id and str(current_job_id) != str(expected_job_id):
                logger.warning(f"⚠️ В очереди другое задание: {current_job_id}")
                # Продолжаем ждать - возможно наше задание следующее

            logger.info(f"⏳ Задание еще печатается... (очередь: {status['jobs_in_queue']})")
            time.sleep(5)

        except Exception as e:
            logger.error(f"Ошибка при проверке статуса печати: {e}")
            time.sleep(5)

    logger.error(f"❌ Таймаут ожидания печати задания {expected_job_id}")
    return False

def print_cups(printer: str, tmp_path: str, job_id: str, timeout: int = 180):
    """
    Отправляем через CUPS и ждем завершения печати.
    """
    result = {
        "job_id": job_id,
        "printer": config.PRINTER_ID,
        "status": "success",
        "error": None
    }

    try:
        # Проверяем существование принтера
        if not printer_exists(printer):
            available_printers = get_available_printers()
            raise Exception(
                f"Принтер '{printer}' не найден в системе CUPS. "
                f"Доступные принтеры: {', '.join(available_printers) if available_printers else 'не найдены'}"
            )

        # Проверяем статус принтера перед отправкой
        printer_status = get_detailed_printer_status(printer)

        # Проверка статусов принтера
        if not printer_status["online"]:
            raise Exception("Принтер не в сети")
        if printer_status.get("paused", False):
            raise Exception("Принтер на паузе")
        if printer_status.get("paper_out", False):
            raise Exception("Нет бумаги")
        if printer_status.get("door_open", False):
            raise Exception("Открыта крышка")

        # Отправляем задание на печать
        lp_result = subprocess.run(
            ["lp", "-d", printer, "-o", "media=A4", tmp_path],
            capture_output=True,
            text=True,
            timeout=30
        )

        if lp_result.returncode != 0:
            error_msg = lp_result.stderr.strip()
            if "The printer or class does not exist" in error_msg:
                available_printers = get_available_printers()
                raise Exception(
                    f"Принтер '{printer}' не существует. "
                    f"Доступные принтеры: {', '.join(available_printers) if available_printers else 'не найдены'}"
                )
            elif "paused" in error_msg.lower():
                raise Exception("Принтер на паузе")
            elif "rejecting" in error_msg.lower():
                raise Exception("Принтер отклоняет задания")
            else:
                raise Exception(f"Ошибка CUPS: {error_msg}")

        # Извлекаем внутренний job_id CUPS
        match = re.search(r"request id is (\S+)", lp_result.stdout)
        cups_job_id = match.group(1) if match else None

        if cups_job_id:
            logger.info(f"📋 CUPS job ID: {cups_job_id}")
        else:
            logger.warning("⚠️ Не удалось извлечь CUPS job ID")

        # Ждем завершения печати
        if not wait_for_print_completion(printer, cups_job_id or job_id, timeout):
            raise Exception("Печать не завершилась в установленное время")

        return result

    except subprocess.TimeoutExpired:
        result.update({
            "status": "error",
            "error": "Таймаут отправки задания на печать"
        })
        return result
    except Exception as e:
        result.update({
            "status": "error",
            "error": str(e)
        })
        return result

def check_printer_ready(printer: str, max_wait: int = 60) -> bool:
    """
    Проверяет, готов ли принтер к печати.
    Возвращает True если готов, False если нет.
    """
    logger.info(f"🔍 Проверяем состояние принтера {printer}...")
    start_time = time.time()

    # Сначала проверяем существование принтера
    if not printer_exists(printer):
        logger.error(f"❌ Принтер {printer} не существует в системе CUPS")
        return False

    # Проверяем статус несколько раз с интервалами
    check_count = 0
    while time.time() - start_time < max_wait:
        check_count += 1
        logger.info(f"🔍 Проверка #{check_count} принтера {printer}...")

        try:
            status = get_detailed_printer_status(printer)

            # Логируем детальный статус для отладки
            logger.info(f"Статус принтера {printer}: online={status['online']}, "
                       f"can_print={status['can_print']}, errors={status['errors']}, "
                       f"jobs_in_queue={status['jobs_in_queue']}")

            # Если принтер полностью недоступен
            if not status["online"] and len(status["errors"]) > 0:
                error_msg = status["errors"][0]

                # Проверяем, является ли ошибка временной
                temporary_errors = ["не в сети", "Принтер недоступен", "Таймаут", "детальный статус недоступен"]
                if any(temp_err in error_msg for temp_err in temporary_errors):
                    logger.info(f"⏳ Временная ошибка: {error_msg}, ждем...")
                    time.sleep(5)
                    continue

                logger.warning(f"❌ Критическая ошибка: {error_msg}")
                return False

            # Проверяем конкретные проблемы
            if status.get("paused", False):
                logger.warning("❌ Принтер на паузе")
                return False

            if status["paper_out"]:
                logger.warning("❌ Нет бумаги")
                return False

            if status["door_open"]:
                logger.warning("❌ Открыта крышка")
                return False

            if status["toner_low"]:
                logger.warning("⚠️ Мало тонера, но продолжаем...")
                # Не блокируем печать при низком тонере, только предупреждаем

            # Если принтер готов и очередь пуста - можно печатать
            if status["can_print"] and status["jobs_in_queue"] == 0:
                logger.info("✅ Принтер готов к печати")
                return True

            # Если есть задания в очереди, ждем их завершения
            if status["jobs_in_queue"] > 0:
                current_job = status.get("current_job_id")
                wait_time = min(10, max_wait - (time.time() - start_time))
                if wait_time > 0:
                    logger.info(f"⏳ Принтер занят заданием {current_job}, "
                               f"ждем {wait_time:.0f} секунд...")
                    time.sleep(min(5, wait_time))
                    continue
                else:
                    logger.warning("⏳ Время ожидания занятого принтера истекло")
                    return False

            # Если принтер онлайн, но не can_print (например, печатает другое задание)
            if status["online"] and not status["can_print"]:
                logger.info("⏳ Принтер онлайн, но занят, ждем...")
                time.sleep(2)
                continue

            # Неизвестное состояние - ждем
            logger.info("⏳ Неизвестное состояние принтера, ждем...")
            time.sleep(3)

        except Exception as e:
            logger.error(f"❌ Ошибка при проверке принтера: {e}")
            time.sleep(5)

    logger.error(f"❌ Принтер {printer} не готов в течение {max_wait} секунд")
    return False

def print_file(task: dict):
    printer = config.PRINTER
    filename = task.get("filename", f"job_{uuid.uuid4().hex}.pdf")
    content_b64 = task.get("content")
    job_id = task.get("job_id", str(uuid.uuid4()))
    tmp_path = os.path.join(tempfile.gettempdir(), filename)

    # Обновляем текущий job_id перед началом печати
    update_current_job_id(task)

    # Базовый ответ с обязательными полями для Laravel
    response = {
        "job_id": job_id,
        "printer": config.PRINTER_ID,
        "status": "success",
        "error": None
    }

    if not content_b64:
        response.update({
            "status": "error",
            "error": "Нет содержимого для печати"
        })
        return response

    try:
        if config.DISABLE_PRINT:
            logger.info("Печать отключена (режим отладки)")
            response["log_status"] = "debug"
            return response

        logger.info(f"🖨️ Начинаем обработку задания {job_id}")

        # Проверяем существование принтера
        if not printer_exists(printer):
            available_printers = get_available_printers()
            error_msg = (
                f"Принтер '{printer}' не найден в системе CUPS. "
                f"Доступные принтеры: {', '.join(available_printers) if available_printers else 'не найдены'}"
            )
            logger.error(error_msg)
            response.update({
                "status": "error",
                "error": error_msg
            })
            return response

        # Проверяем готовность принтера
        if not check_printer_ready(printer):
            response.update({
                "status": "error",
                "error": "Принтер не готов к печати"
            })
            return response

        # Сохраняем файл
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(content_b64))
        logger.info(f"💾 Файл сохранен: {tmp_path}")

        # Выполняем печать
        logger.info(f"🚀 Отправляем задание {job_id} на печать...")
        print_result = print_cups(printer, tmp_path, job_id)

        # Обновляем ответ
        response.update(print_result)

        if response["status"] == "success":
            logger.info(f"🎉 Задание {job_id} успешно распечатано")
        else:
            logger.error(f"❌ Ошибка печати задания {job_id}: {response['error']}")

        return response

    except Exception as e:
        error_msg = f"Критическая ошибка: {str(e)}"
        logger.error(f"❌ {error_msg}\n{traceback.format_exc()}")
        response.update({
            "status": "error",
            "error": error_msg
        })
        return response
    finally:
        # Очищаем текущий job_id после завершения печати
        update_current_job_id({})
        # Удаляем временный файл
        cleanup_file(tmp_path)
