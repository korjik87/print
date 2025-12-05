import threading
import time
from datetime import datetime, timezone
import requests
from . import config
from .utils import get_printer_status, get_detailed_printer_status, get_current_job_id


def send_heartbeat(logger=None):
    while True:
        try:
            printer_worker = config.PRINTER
            url = f"{config.LARAVEL_API}/v1/worker-status"
            status = get_detailed_printer_status(printer_worker)
            job_id = get_current_job_id()

            # Проверяем состояние RabbitMQ соединения
            rabbitmq_data = {
                "status": "unknown",
                "last_check": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "error_message": None,
                "error_count": 0
            }

            try:
                # Глобальные переменные из rabbit.py
                from .rabbit import connection, channel

                if connection is None or connection.is_closed:
                    rabbitmq_data["status"] = "disconnected"
                    rabbitmq_data["error_message"] = "Соединение с RabbitMQ разорвано"
                elif channel is None or channel.is_closed:
                    rabbitmq_data["status"] = "disconnected"
                    rabbitmq_data["error_message"] = "Канал RabbitMQ закрыт"
                else:
                    rabbitmq_data["status"] = "connected"

            except Exception as e:
                rabbitmq_data["status"] = "error"
                rabbitmq_data["error_message"] = f"Ошибка при проверке соединения: {str(e)}"

            data = {
                "worker_id": config.PRINTER_ID,
                "printer_id": printer_worker,
                "job_id": job_id,
                "printer_status": status,
                "rabbitmq_status": rabbitmq_data,  # отправляем JSON объект
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }

            r = requests.post(
                url,
                json=data,
                headers={"Authorization": f"Bearer {config.LARAVEL_TOKEN}"},
                timeout=5
            )

            if r.status_code != 200:
                if logger:
                    logger.error(f"[heartbeat] Ошибка {r.status_code}: {r.text}")
                else:
                    print(f"[heartbeat] Ошибка {r.status_code}: {r.text}")

            if logger:
                logger.info(f"Отправлен heartbeat")
            else:
                print(f"Отправлен heartbeat")

        except Exception as e:
            if logger:
                logger.error(f"Ошибка heartbeat: {e}")
            else:
                print(f"Ошибка heartbeat: {e}")

        time.sleep(config.HEARTBEAT_INTERVAL)


def start_heartbeat_thread(logger=None):
    t = threading.Thread(target=send_heartbeat, args=(logger,), daemon=True)
    t.start()
