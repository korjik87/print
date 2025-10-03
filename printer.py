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
from .utils import cleanup_file
from .utils import get_printer_status, get_detailed_printer_status


def print_raw(printer: str, tmp_path: str):
    cmd = ["nc", "-w1", printer, "9100"]
    with open(tmp_path, "rb") as f:
        result = subprocess.run(cmd, input=f.read(), capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="ignore").strip()
        cli = f"nc -w1 {printer} < {tmp_path}"
        raise Exception(f"Ошибка RAW-печати: {stderr}, cmd: {cli}")


def print_cups(printer: str, tmp_path: str, timeout: int = 120):
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

    # Парсим job-id
    stdout = result.stdout.strip()
    # Ожидаем строку вида: "request id is printer-123 (1 file(s))"
    match = re.search(r"request id is (\S+)", stdout)
    job_id = match.group(1) if match else None

    # Необязательный мониторинг (чисто для логов)
    log_status = None
    if job_id:
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = subprocess.run(
                ["lpstat", "-W", "not-completed", "-o", printer],
                capture_output=True,
                text=True
            )
            if job_id not in status.stdout:
                break
            time.sleep(1)

        completed = subprocess.run(
            ["lpstat", "-W", "completed", "-o", printer],
            capture_output=True,
            text=True
        )
        if job_id in completed.stdout:
            log_status = "completed"
        else:
            log_status = "unknown"

    return {
        "job_id": job_id,
        "status": "success",  # если lp отработал без ошибок
        "log_status": log_status,
    }


def print_file(task: dict):
    printer = str(task.get("printer", config.PRINTER))
    printer_worker = config.PRINTER
    method = config.DEFAULT_METHOD
    job_id = task.get("job_id", str(uuid.uuid4()))
    content_b64 = task.get("content")
    filename = task.get("filename", f"print_job_{uuid.uuid4().hex}.pdf")

    if not content_b64:
        return {
            "file": None,
            "printer": printer,
            "printer_worker": printer_worker,
            "job_id": job_id,
            "method": method,
            "status": "error",
            "error": "Нет содержимого файла (content)",
            "log_status": None,
            "printer_status": get_detailed_printer_status(printer_worker),
        }

    tmp_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(content_b64))

        # Проверяем статус принтера
        printer_status = get_detailed_printer_status(printer_worker)
        if not printer_status["online"]:
            raise Exception("Принтер не в сети или отключен")
        if printer_status["paper_out"]:
            raise Exception("Нет бумаги в принтере")
        if printer_status["door_open"]:
            raise Exception("Открыта крышка принтера")
        if printer_status.get("error"):
            raise Exception(f"Ошибка статуса принтера: {printer_status['error']}")


        if config.DISABLE_PRINT:
            status, error, log_status = "success", None, "print disabled"
        elif method == "raw":
            print_raw(printer_worker, tmp_path)
            status, error, log_status = "success", None, "raw sent"
        elif method == "cups":
            job_id, log_status = print_cups(printer_worker, tmp_path)
            status, error = "success", None
        else:
            raise Exception(f"Неизвестный метод печати: {method}")

    except Exception as e:
        status, error, log_status = "error", str(e), None
    finally:
        cleanup_file(tmp_path)

    return {
        "file": filename,
        "printer": printer,
        "printer_worker": printer_worker,
        "job_id": job_id,
        "method": method,
        "status": status,
        "error": error,
        "log_status": log_status,
        "printer_status": get_detailed_printer_status(printer_worker)
    }
