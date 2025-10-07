import pika
import json
import sys
import time
import traceback

from . import config
from .printer import print_file
from .callback import send_callback
from .utils import setup_logger

logger = setup_logger()

connection = None
channel = None


def process_task(task):
    """
    Обработка одной задачи печати.
    Возвращает:
      - True, если напечатано успешно
      - False, если нужно повторить позже
    """
    result = print_file(task)
    send_callback(result)

    if result["status"] == "success":
        logger.info(f"[OK] Задача {result['job_id']} успешно напечатана.")
        return True
    else:
        logger.warning(f"[WAIT] Принтер недоступен: {result['error']}")
        return False


def callback(ch, method, properties, body):
    """
    Обработчик входящих сообщений из RabbitMQ.
    """
    try:
        task = json.loads(body.decode())
    except Exception as e:
        logger.error(f"Ошибка: неверный формат задачи ({e})")
        print("Ошибка: неверный формат задачи", e, file=sys.stderr)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    while True:
        try:
            success = process_task(task)
            if success:
                ch.basic_ack(delivery_tag=method.delivery_tag)
                break
            else:
                # Если принтер недоступен — ждём 15 сек и проверяем снова
                time.sleep(15)
        except Exception as e:
            logger.error(f"Ошибка обработки задачи: {e}\n{traceback.format_exc()}")
            time.sleep(10)


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

    logger.info(f"🖨️  Worker запущен для очереди {queue_name}")
    channel.start_consuming()
