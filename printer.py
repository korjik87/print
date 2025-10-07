import subprocess
import tempfile
import os
import base64
import uuid
import time
import shutil
import re
import time

from . import config
from .utils import cleanup_file, get_detailed_printer_status, setup_logger

logger = setup_logger()

def print_raw(printer: str, tmp_path: str):
    cmd = ["nc", "-w1", printer, "9100"]
    with open(tmp_path, "rb") as f:
        result = subprocess.run(cmd, input=f.read(), capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="ignore").strip()
        cli = f"nc -w1 {printer} < {tmp_path}"
        raise Exception(f"Ошибка RAW-печати: {stderr}, cmd: {cli}")


def wait_until_ready(printer_name: str, max_wait: int = 300, interval: int = 10):
    """
    Ждём, пока принтер будет готов к печати.
    Возвращает True, если готов, иначе False по таймауту.
    """
    start_time = time.time()
    while time.time() - start_time < max_wait:
        status = get_detailed_printer_status(printer_name)
        if (
            status["online"]
            and not status["paper_out"]
            and not status["door_open"]
            and status["jobs_in_queue"] == 0
        ):
            return True
        logger.info(f"⏳ Принтер не готов, ждём... ({status['raw_status'][:80]}...)")
        time.sleep(interval)
    return False


def print_cups(printer: str, tmp_path: str, timeout: int = 180):
    """
    Отправляем через CUPS.
    Основное решение — exit-код lp.
    Статус задачи через lpstat используется только для логов.
    """
    result = subprocess.run(
        ["lp", "-d", printer, "-o", "media=A4", tmp_path],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise Exception(f"Ошибка CUPS: {result.stderr.strip()}")

    match = re.search(r"request id is (\S+)", result.stdout)
    job_id = match.group(1) if match else None

    start = time.time()
    while time.time() - start < timeout:
        status = subprocess.run(["lpstat", "-W", "not-completed", "-o", printer],
                                capture_output=True, text=True)
        if job_id not in status.stdout:
            return {"job_id": job_id, "status": "success"}
        time.sleep(2)

    raise Exception("Печать не завершилась в установленное время")


def print_file(task: dict):
    printer = config.PRINTER
    filename = task.get("filename", f"job_{uuid.uuid4().hex}.pdf")
    content_b64 = task.get("content")
    job_id = task.get("job_id", str(uuid.uuid4()))

    if not content_b64:
        return {"status": "error", "error": "Нет содержимого"}

    try:
        if config.DISABLE_PRINT:
            logger.info("Печать отключена (режим отладки)")
            return {"status": "success", "job_id": job_id, "log_status": "debug"}




        # Проверяем состояние принтера
        status = get_detailed_printer_status(printer)
        if not status["online"]:
            raise Exception("Принтер не в сети")
        if status["jobs_in_queue"] > 0:
            raise Exception("Очередь печати не пуста")
        if status["paper_out"]:
            raise Exception("Нет бумаги")
        if status["door_open"]:
            raise Exception("Открыта крышка")


        tmp_path = os.path.join(tempfile.gettempdir(), filename)
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(content_b64))


        # Основная печать
        logger.info(f"🖨️ Отправляем задачу {job_id} на принтер {printer}...")
        result = print_cups(printer, tmp_path)
        result.update({"status": "success"})
        return result

    except Exception as e:
        logger.warning(f"Ошибка при печати: {e}")
        return {"status": "error", "error": str(e), "printer_status": status}
    finally:
        if os.path.isfile(tmp_path):
            cleanup_file(tmp_path)
