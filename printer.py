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

logger = setup_logger()

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
        # Отправляем задание на печать
        lp_result = subprocess.run(
            ["lp", "-d", printer, "-o", "media=A4", tmp_path],
            capture_output=True,
            text=True
        )

        if lp_result.returncode != 0:
            raise Exception(f"Ошибка CUPS: {lp_result.stderr.strip()}")

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

    except Exception as e:
        result.update({
            "status": "error",
            "error": str(e)
        })
        return result

def check_printer_ready(printer: str, max_wait: int = 60):
    """
    Проверяет, готов ли принтер к печати.
    Возвращает True если готов, False если нет.
    """
    logger.info(f"🔍 Проверяем состояние принтера {printer}...")
    start_time = time.time()

    while time.time() - start_time < max_wait:
        try:
            status = get_detailed_printer_status(printer)

            if not status["online"]:
                logger.warning("Принтер не в сети")
                return False

            if status["paper_out"]:
                logger.warning("Нет бумаги")
                return False

            if status["door_open"]:
                logger.warning("Открыта крышка")
                return False

            # Если принтер готов и очередь пуста - можно печатать
            if status["can_print"] and status["jobs_in_queue"] == 0:
                logger.info("✅ Принтер готов к печати")
                return True

            # Если есть задания в очереди, ждем их завершения
            if status["jobs_in_queue"] > 0:
                current_job = status.get("current_job_id")
                logger.info(f"⏳ Принтер занят заданием {current_job}, ждем...")
                time.sleep(5)
                continue

            time.sleep(2)

        except Exception as e:
            logger.error(f"Ошибка при проверке принтера: {e}")
            time.sleep(5)

    logger.error("❌ Принтер не готов в течение заданного времени")
    return False

def print_file(task: dict):
    printer = config.PRINTER
    filename = task.get("filename", f"job_{uuid.uuid4().hex}.pdf")
    content_b64 = task.get("content")
    job_id = task.get("job_id", str(uuid.uuid4()))
    tmp_path = os.path.join(tempfile.gettempdir(), filename)

    # Обновляем текущий job_id перед началом печати
    update_current_job_id(task)

    # Базовый ответ
    response = {
        "job_id": job_id,
        "printer": printer,
        "status": "success"
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
