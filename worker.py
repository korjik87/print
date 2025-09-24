import pika
import subprocess
import json
import requests
import signal
import sys
import os
import base64
import tempfile
import uuid
import config

MY_PRINTER_ID = str(config.PRINTER_ID)  # id своего принтера
QUEUE_NAME = f"print_tasks_printer_{MY_PRINTER_ID}"


connection = None
channel = None
queue_name = None


def send_callback(result: dict):
    """Отправка результата в Laravel API"""
    try:
        url = f"{config.LARAVEL_API}/api/v1/print-callback"
        requests.post(url, json=result, timeout=5)
    except Exception as e:
        print("Ошибка при возврате результата:", e, file=sys.stderr)


def print_file(task):
    printer = str(task.get("printer"))
    method = task.get("method", "raw")
    job_id = task.get("job_id", str(uuid.uuid4()))

    content_b64 = task.get("content")
    filename = task.get("filename", f"print_job_{uuid.uuid4().hex}.pdf")

    if not content_b64:
        return {
            "file": None,
            "printer": printer,
            "job_id": job_id,
            "method": method,
            "status": "error",
            "error": "Нет содержимого файла (content)"
        }

    # создаём временный файл
    tmp_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(content_b64))

        if method == "raw":
            # отправляем содержимое напрямую в принтер через nc
            cmd = ["nc", "-w1", config.PRINTER, "9100"]
            with open(tmp_path, "rb") as f:
                result = subprocess.run(
                    cmd,
                    input=f.read(),
                    capture_output=True
                )

            if result.returncode != 0:
                stderr = result.stderr.decode(errors="ignore").strip()
                cli =  f"nc -w1 {config.PRINTER} < {tmp_path}"

                raise Exception(
                    f"Ошибка печати (RAW): код {result.returncode}, stderr: {stderr}, cmd: {cli}"
                )

        elif method == "cups":
            cmd = ["lp", "-d", config.PRINTER, tmp_path]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                raise Exception(
                    f"Ошибка печати (CUPS): код {result.returncode}, stderr: {result.stderr.strip()}"
                )

        else:
            raise Exception(f"Неизвестный метод печати: {method}")

        status = "success"
        error = None

    except Exception as e:
        status = "error"
        error = str(e)

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return {
        "file": filename,
        "printer": printer,
        "job_id": job_id,
        "method": method,
        "status": status,
        "error": error
    }


def callback(ch, method, properties, body):
    try:
        task = json.loads(body.decode())
    except Exception as e:
        print("Ошибка: неверный формат задачи", e, file=sys.stderr)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    result = print_file(task)
    send_callback(result)

    ch.basic_ack(delivery_tag=method.delivery_tag)
    print("Результат:", result)


def graceful_exit(signum, frame):
    global connection, channel
    print("\n [*] Останавливаю worker...")

    try:
        if channel and channel.is_open:
            channel.close()
            print(" [*] Канал закрыт")
        if connection and connection.is_open:
            connection.close()
            print(" [*] Соединение закрыто")
    except Exception as e:
        print(" [!] Ошибка при закрытии:", e)

    sys.exit(0)


signal.signal(signal.SIGINT, graceful_exit)
signal.signal(signal.SIGTERM, graceful_exit)


def main():
    global connection, channel, queue_name

    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=config.RABBIT_HOST, port=config.RABBIT_PORT)
    )
    channel = connection.channel()

    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True,       # очередь сохраняется при рестарте
        exclusive=False,
        auto_delete=False
    )

    channel.basic_qos(prefetch_count=1)  # по 1 задаче на воркер
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)

    print(f" [*] Worker {MY_PRINTER_ID} запущен. Очередь: {QUEUE_NAME}")
    channel.start_consuming()


if __name__ == "__main__":
    main()
