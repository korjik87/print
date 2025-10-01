import threading
import time
import requests
import config
from utils import get_printer_status

def send_heartbeat():
    printer_worker = config.PRINTER
    while True:
        status = get_printer_status(printer)
        payload = {
            "worker_id": config.WORKER_ID,
            "printer_id": printer,
            "printer_status": status,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        try:
            r = requests.post(
                f"{config.LARAVEL_API}/v1/worker-status",
                json=payload,
                headers={"Authorization": f"Bearer {config.API_TOKEN}"},
                timeout=5
            )
            if r.status_code != 200:
                print(f"[heartbeat] Ошибка {r.status_code}: {r.text}")
        except Exception as e:
            print(f"[heartbeat] Не удалось отправить статус: {e}")

        time.sleep(config.HEARTBEAT_INTERVAL)


def start_heartbeat_thread():
    t = threading.Thread(target=send_heartbeat, daemon=True)
    t.start()
