import requests
import sys
from . import config
from .utils import get_current_job_id


def send_callback(result: dict):
    """Отправка результата в Laravel API"""
    try:
        url = f"{config.LARAVEL_API}/v1/print-callback"
        headers = {
            "Authorization": f"Bearer {config.LARAVEL_TOKEN}",
            "Accept": "application/json"
        }
        data = {
            "job_id": get_current_job_id(),
        }

        response = requests.post(url, json=data, headers=headers, timeout=5)

        if response.status_code != 200:
            print(f"[!] Ошибка callback: {response.status_code} {response.text}", file=sys.stderr)

    except Exception as e:
        print("Ошибка при возврате результата:", e, file=sys.stderr)
