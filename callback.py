import requests
import sys
import traceback
from . import config
from .utils import setup_logger

logger = setup_logger()

def send_callback(result: dict):
    """Отправка результата в Laravel API"""
    try:
        url = f"{config.LARAVEL_API}/v1/print-callback"
        headers = {
            "Authorization": f"Bearer {config.LARAVEL_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        # Используем job_id из результата, а не из глобального состояния
        data = {
            "job_id": result.get("job_id"),
            "status": result.get("status"),
            "error": result.get("error", "")
        }

        logger.info(f"Отправка callback для задачи {data['job_id']}: {data['status']}")

        response = requests.post(url, json=data, headers=headers, timeout=10)

        if response.status_code == 200:
            logger.info(f"✅ Callback успешно отправлен для задачи {data['job_id']}")
        else:
            logger.error(f"❌ Ошибка callback: {response.status_code} {response.text}")

    except requests.exceptions.Timeout:
        logger.error("⚠️ Timeout при отправке callback")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке callback: {e}\n{traceback.format_exc()}")
