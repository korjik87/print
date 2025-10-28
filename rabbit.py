import pika
import json
import sys
import time
import traceback

from . import config
from .printer import print_file
from .callback import send_callback
from .utils import setup_logger, update_current_job_id

logger = setup_logger()

connection = None
channel = None

def process_task(task):
    """
    Обработка одной задачи печати.
    Возвращает:
      - True, если напечатано успешно
      - False, если нужно повторить позже (временная ошибка)
      - None, если фатальная ошибка (не повторять)
    """
    try:
        result = print_file(task)
    except Exception as e:
        logger.error(f"Критическая ошибка в print_file: {e}\n{traceback.format_exc()}")
        send_callback({
            "status": "error",
            "job_id": task.get("job_id"),
            "error": f"Критическая ошибка: {str(e)}"
        })
        return None

    if result["status"] == "success":
        send_callback(result)
        logger.info(f"[OK] Задача {result['job_id']} успешно напечатана.")
        update_current_job_id({})
        return True
    else:
        error_msg = result.get("error", "")
        logger.warning(f"[ERROR] Ошибка печати: {error_msg}")

        # Временные ошибки (повторяем)
        temporary_errors = [
            "недоступен", "timeout", "wait", "занят",
            "очередь", "busy", "unavailable"
        ]

        if any(keyword in error_msg.lower() for keyword in temporary_errors):
            return False  # Временная ошибка - повторяем
        else:
            # Фатальная ошибка - не повторяем
            send_callback({
                "status": "error",
                "job_id": task.get("job_id"),
                "error": error_msg
            })
            return None

def wait_with_connection_check(seconds, connection):
    """
    Ожидание с проверкой соединения
    Возвращает True если соединение активно, False если разорвано
    """
    interval = 0.5
    steps = int(seconds / interval)
    for i in range(steps):
        if connection is None or connection.is_closed:
            return False
        time.sleep(interval)
        # Периодически обрабатываем события соединения
        if i % 10 == 0:  # Каждые 5 секунд
            try:
                connection.process_data_events()
            except:
                return False
    return True

def callback(ch, method, properties, body):
    """
    Обработчик входящих сообщений из RabbitMQ.
    """
    global connection

    try:
        task = json.loads(body.decode())
        logger.info(f"Получена задача: {task.get('job_id', 'unknown')}")
    except Exception as e:
        logger.error(f"Ошибка: неверный формат задачи ({e})")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    max_retries = 5  # Уменьшено количество попыток
    retry_count = 0

    while retry_count <= max_retries:
        try:
            # Проверяем соединение перед обработкой
            if connection is None or connection.is_closed:
                logger.warning("Соединение разорвано, прерываем обработку задачи")
                return

            result = process_task(task)

            if result is True:
                # Успех - подтверждаем сообщение
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return
            elif result is False:
                # Временная ошибка - повторяем после ожидания
                retry_count += 1
                if retry_count <= max_retries:
                    logger.info(f"Повторная попытка {retry_count}/{max_retries} через 15 сек")
                    if not wait_with_connection_check(15, connection):
                        logger.warning("Соединение разорвано во время ожидания")
                        return
                else:
                    logger.warning(f"Превышено количество попыток для задачи {task.get('job_id')}")
                    # Возвращаем задачу в очередь
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    return
            else:
                # Фатальная ошибка - подтверждаем и не повторяем
                logger.error(f"Фатальная ошибка для задачи {task.get('job_id')}")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

        except Exception as e:
            logger.error(f"Ошибка обработки задачи: {e}\n{traceback.format_exc()}")
            retry_count += 1
            if retry_count <= max_retries:
                if not wait_with_connection_check(10, connection):
                    return
            else:
                logger.error("Превышено количество попыток из-за исключений")
                try:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                except:
                    logger.error("Не удалось отправить NACK - соединение разорвано")
                return

    # Если вышли из цикла - возвращаем в очередь
    try:
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
    except:
        logger.error("Не удалось отправить NACK - соединение разорвано")

def create_connection():
    """Создает новое соединение с увеличенным heartbeat"""
    credentials = pika.PlainCredentials(
        username=config.RABBIT_USER,
        password=config.RABBIT_PASS
    )

    parameters = pika.ConnectionParameters(
        host=config.RABBIT_HOST,
        port=config.RABBIT_PORT,
        credentials=credentials,
        heartbeat=600,  # Увеличено до 10 минут
        blocked_connection_timeout=300,  # Таймаут для блокированных соединений
        connection_attempts=3,  # Количество попыток подключения
        retry_delay=5  # Задержка между попытками
    )

    return pika.BlockingConnection(parameters)

def start_rabbit():
    global connection, channel

    reconnect_delay = 5  # Начальная задержка переподключения
    max_reconnect_delay = 60  # Максимальная задержка

    while True:
        try:
            logger.info(f"Попытка подключения к RabbitMQ...")
            connection = create_connection()
            channel = connection.channel()

            queue_name = f"print_tasks_printer_{config.PRINTER_ID}"
            channel.queue_declare(queue=queue_name, durable=True, exclusive=False, auto_delete=False)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=queue_name, on_message_callback=callback)

            logger.info(f"✅ Успешное подключение к RabbitMQ. Очередь: {queue_name}")
            logger.info(f"✅ Heartbeat установлен на 600 секунд")

            # Сброс задержки переподключения при успешном подключении
            reconnect_delay = 5

            # Запуск потребления сообщений
            channel.start_consuming()

        except pika.exceptions.AMQPHeartbeatTimeout:
            logger.error("❌ Heartbeat timeout - соединение разорвано")

        except pika.exceptions.AMQPConnectionError as e:
            logger.error(f"❌ Ошибка подключения к RabbitMQ: {e}")

        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка: {e}\n{traceback.format_exc()}")

        # Закрытие соединения при ошибке
        try:
            if connection and connection.is_open:
                connection.close()
        except:
            pass

        logger.info(f"🔄 Переподключение через {reconnect_delay} секунд...")
        time.sleep(reconnect_delay)

        # Увеличение задержки для следующей попытки (exponential backoff)
        reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
