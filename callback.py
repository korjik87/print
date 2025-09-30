import requests
import sys


def send_callback(result: dict):
    """Отправка результата в Laravel API"""
    try:
        url = f"{config.LARAVEL_API}/api/v1/print-callback"
        response = requests.post(url, json=result, timeout=5)

        if response.status_code != 200:
            print(f"[!] Ошибка callback: {response.status_code} {response.text}", file=sys.stderr)

    except Exception as e:
        print("Ошибка при возврате результата:", e, file=sys.stderr)
