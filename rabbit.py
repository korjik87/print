import pika
import json
import sys

from . import config
from .printer import print_file
from .callback import send_callback

connection = None
channel = None


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


def start_rabbit():
    global connection, channel

    credentials = pika.PlainCredentials(
        username=config.RABBIT_USER,
        password=config.RABBIT_PASS
    )
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=config.RABBIT_HOST,
            port=config.RABBIT_PORT,
            credentials=credentials
        )
    )
    channel = connection.channel()
    queue_name = f"print_tasks_printer_{config.PRINTER_ID}"

    channel.queue_declare(queue=queue_name, durable=True, exclusive=False, auto_delete=False)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=queue_name, on_message_callback=callback)

    channel.start_consuming()
