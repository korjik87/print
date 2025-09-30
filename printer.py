import subprocess
import tempfile
import os
import base64
import uuid
import time
import shutil

from . import config
from .utils import cleanup_file


def print_raw(printer: str, tmp_path: str):
    cmd = ["nc", "-w1", printer, "9100"]
    with open(tmp_path, "rb") as f:
        result = subprocess.run(cmd, input=f.read(), capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="ignore").strip()
        cli = f"nc -w1 {printer} < {tmp_path}"
        raise Exception(f"Ошибка RAW-печати: {stderr}, cmd: {cli}")


def print_cups(printer: str, tmp_path: str):
    """Отправляем через CUPS и ждём завершения"""
    result = subprocess.run(
        ["lp", "-d", printer, "-o", "media=A4", tmp_path],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise Exception(f"Ошибка CUPS: {result.stderr.strip()}")

    # Парсим job-id
    stdout = result.stdout.strip()
    # обычно строка вида: "request id is printer-123 (1 file(s))"
    try:
        job_id = stdout.split(" ")[3]  # printer-123
    except Exception:
        raise Exception(f"Не удалось получить job-id: {stdout}")

    # Ожидаем завершения
    for _ in range(60):  # ждём максимум 60 сек
        status = subprocess.run(
            ["lpstat", "-W", "not-completed", "-o", printer],
            capture_output=True,
            text=True
        )
        if job_id not in status.stdout:
            break
        time.sleep(1)

    # Проверим ошибки в истории
    completed = subprocess.run(
        ["lpstat", "-W", "completed", "-o", printer],
        capture_output=True,
        text=True
    )
    if job_id not in completed.stdout:
        raise Exception(f"Задача {job_id} не найдена среди завершённых")

    return job_id


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
            "error": "Нет содержимого файла (content)"
        }

    tmp_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(content_b64))

        if config.DISABLE_PRINT:
            status, error = "success", None
        elif method == "raw":
            print_raw(printer_worker, tmp_path)
            status, error = "success", None
        elif method == "cups":
            job_id = print_cups(printer_worker, tmp_path)
            status, error = "success", None
        else:
            raise Exception(f"Неизвестный метод печати: {method}")

    except Exception as e:
        status, error = "error", str(e)
    finally:
        cleanup_file(tmp_path)

    return {
        "file": filename,
        "printer": printer,
        "printer_worker": printer_worker,
        "job_id": job_id,
        "method": method,
        "status": status,
        "error": error
    }
