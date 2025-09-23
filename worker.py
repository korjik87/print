import pika, subprocess, json, requests, sys, os, base64, tempfile, uuid
import config

MY_PRINTER_ID = config.PRINTER_ID  # id своего принтера


def print_file(task):
    printer = str(task.get("printer"))
    method = task.get("method", "raw")

    content_b64 = task.get("content")
    filename = task.get("filename", f"print_job_{uuid.uuid4().hex}.pdf")

    if not content_b64:
        return {
            "file": None,
            "printer": printer,
            "method": method,
            "status": "error",
            "error": "Нет содержимого файла (content)"
        }

    # создаём временный файл
    tmp_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(content_b64))

        # выполняем печать
        if method == "raw":
            # nc -w1 192.168.50.131 9100 < file.pdf
            cmd = f"nc -w1 {config.PRINTERS[printer]} < {tmp_path}"
            subprocess.run(cmd, shell=True, check=True)

        elif method == "cups":
            subprocess.run(["lp", "-d", config.PRINTERS[printer], tmp_path], check=True)
        else:
            raise Exception(f"Неизвестный метод печати: {method}")

        status = "success"
        error = None

    except subprocess.CalledProcessError as e:
        status = "error"
        error = str(e)
    except Exception as e:
        status = "error"
        error = str(e)
    finally:
        # удаляем временный файл
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return {
        "file": filename,
        "printer": printer,
        "method": method,
        "status": status,
        "error": error
    }


def callback(ch, method, properties, body):
    try:
        task = json.loads(body.decode())
    except Exception as e:
        print("Ошибка: неверный формат задачи", e)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    # фильтруем задачи по своему принтеру
    if str(task.get("printer")) != str(MY_PRINTER_ID):
        # не подтверждаем, возвращаем в очередь
        print(f" [*] Worker {MY_PRINTER_ID}: задача для {task.get('printer')}, пропускаю")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        return

    result = print_file(task)

    # Отправляем результат обратно в Laravel API
    try:
        requests.post(config.LARAVEL_API, json=result, timeout=5)
    except Exception as e:
        print("Ошибка при возврате результата:", e, file=sys.stderr)

    # подтверждаем обработку ???????
    ch.basic_ack(delivery_tag=method.delivery_tag)

    print("Результат:", result)


def main():
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=config.RABBIT_HOST, port=config.RABBIT_PORT)
    )
    channel = connection.channel()
    channel.queue_declare(queue=config.RABBIT_QUEUE, durable=False)

    channel.basic_consume(
        queue=config.RABBIT_QUEUE,
        on_message_callback=callback,
        auto_ack=False
    )

    print(f" [*] Worker {MY_PRINTER_ID} запущен. Жду задачи...")
    channel.start_consuming()


if __name__ == "__main__":
    main()
