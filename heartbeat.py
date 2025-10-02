import threading
import time
import requests
from . import config
from .utils import get_printer_status


def send_heartbeat(logger=None):
    while True:
        try:
            printer_worker = config.PRINTER
            url = f"{config.LARAVEL_API}/v1/worker-status"
            status = get_printer_status(printer_worker)
            data = {
                "worker_id": config.PRINTER_ID,
                "printer_id": printer_worker,
                "printer_status": status,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }

            r = requests.post(
                url,
                json=data,
                headers={"Authorization": f"Bearer {config.LARAVEL_TOKEN}"},
                timeout=5
            )

            if r.status_code != 200:
                print(f"[heartbeat] Ошибка {r.status_code}: {r.text}")

            if logger:
                logger.info(f"Отправлен heartbeat: {data}")
            else:
                print(f"Отправлен heartbeat: {data}")
        except Exception as e:
            if logger:
                logger.error(f"Ошибка heartbeat: {e}")
            else:
                print(f"Ошибка heartbeat: {e}")
        time.sleep(config.HEARTBEAT_INTERVAL)


def start_heartbeat_thread(logger=None):
    t = threading.Thread(target=send_heartbeat, args=(logger,), daemon=True)
    t.start()
