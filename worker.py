import pika, subprocess, json, requests, sys
import config

# Каждый воркер хранит свой принтер ID
MY_PRINTER_ID = config.MY_PRINTER_ID  # например, 1

def print_file(task):
    file_path = task.get("file_path")
    printer = config.DEFAULT_PRINTER
    printer_id = task.get("printer_id", config.DEFAULT_PRINTER)
    method = task.get("method", config.DEFAULT_METHOD)

    try:
        if method == "raw":
            # nc -w1 192.168.50.131 9100 < file.pdf
            cmd = f"nc -w1 {printer} < {file_path}"
            subprocess.run(cmd, shell=True, check=True)

        elif method == "cups":
            # lp -d OfficePrinter file.pdf
            subprocess.run(["lp", "-d", printer, file_path], check=True)

        else:
            raise Exception(f"Unknown print method: {method}")

        status = "success"
        error = None

    except subprocess.CalledProcessError as e:
        status = "error"
        error = str(e)
    except Exception as e:
        status = "error"
        error = str(e)

    return {
        "file": file_path,
        "printer": printer,
        "printer_id": printer_id,
        "method": method,
        "status": status,
        "error": error
    }


def callback(ch, method, properties, body):
    print(f" Worker ")

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

    # Отправляем обратно в Laravel API
    try:
        requests.post(config.LARAVEL_API, json=result, timeout=5)
    except Exception as e:
        print("Ошибка при возврате результата:", e, file=sys.stderr)

    print("Результат:", result)


def main():
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=config.RABBIT_HOST, port=config.RABBIT_PORT)
    )
    channel = connection.channel()
    channel.queue_declare(queue=config.RABBIT_QUEUE)

    channel.basic_consume(
        queue=config.RABBIT_QUEUE,
        on_message_callback=callback,
        auto_ack=False
    )

    print(f" [*] Worker для принтера {MY_PRINTER_ID} запущен. Жду задачи...")
    channel.start_consuming()


if __name__ == "__main__":
    main()
