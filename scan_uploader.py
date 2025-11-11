import requests
import json
import logging
from typing import Dict, Optional
import time
import os

import config
from utils import setup_logger

logger = setup_logger()

class ScanUploader:
    def __init__(self):
        self.base_url = config.LARAVEL_API.rstrip('/')
        self.token = config.LARAVEL_TOKEN
        self.upload_endpoint = config.SCAN_UPLOAD_ENDPOINT

    def upload_scan(self, scan_result: Dict) -> Dict:
        """
        Отправляет отсканированный файл в Laravel Apiato
        Возвращает результат отправки
        """
        result = {
            "upload_status": "success",
            "error": None,
            "response_data": None,
            "scan_id": scan_result.get("scan_id")
        }

        if not self.token:
            error_msg = "LARAVEL_TOKEN не установлен. Не могу отправить скан."
            logger.error(f"❌ {error_msg}")
            result.update({
                "upload_status": "error",
                "error": error_msg
            })
            return result

        if not scan_result.get("content"):
            error_msg = "Нет данных скана для отправки."
            logger.error(f"❌ {error_msg}")
            result.update({
                "upload_status": "error",
                "error": error_msg
            })
            return result

        try:
            # Подготавливаем данные для отправки
            upload_url = f"{self.base_url}{self.upload_endpoint}"

            # Создаем multipart/form-data
            files = {
                'scan_file': (
                    scan_result['filename'],
                    scan_result['content'].encode('utf-8'),  # base64 строка
                    'application/octet-stream'
                )
            }

            # Дополнительные данные
            data = {
                'scan_id': scan_result['scan_id'],
                'filename': scan_result['filename'],
                'scan_format': 'pdf' if scan_result['filename'].endswith('.pdf') else 'png',
                'scan_dpi': config.SCANNER_DPI,
                'scan_mode': config.SCANNER_MODE,
                'timestamp': int(time.time())
            }

            headers = {
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/json'
            }

            logger.info(f"📤 Отправка скана {scan_result['scan_id']} на {upload_url}")

            # Отправляем запрос
            response = requests.post(
                upload_url,
                files=files,
                data=data,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"✅ Скан успешно отправлен. Ответ: {response_data}")
                result["response_data"] = response_data
            elif response.status_code == 201:
                response_data = response.json()
                logger.info(f"✅ Скан успешно создан. Ответ: {response_data}")
                result["response_data"] = response_data
            else:
                error_msg = f"Ошибка сервера: {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                result.update({
                    "upload_status": "error",
                    "error": error_msg
                })

        except requests.exceptions.ConnectionError as e:
            error_msg = f"Ошибка подключения к серверу: {e}"
            logger.error(f"❌ {error_msg}")
            result.update({
                "upload_status": "error",
                "error": error_msg
            })
        except requests.exceptions.Timeout as e:
            error_msg = "Таймаут при отправке скана"
            logger.error(f"❌ {error_msg}")
            result.update({
                "upload_status": "error",
                "error": error_msg
            })
        except requests.exceptions.RequestException as e:
            error_msg = f"Ошибка при отправке запроса: {e}"
            logger.error(f"❌ {error_msg}")
            result.update({
                "upload_status": "error",
                "error": error_msg
            })
        except Exception as e:
            error_msg = f"Неизвестная ошибка при отправке скана: {e}"
            logger.error(f"❌ {error_msg}")
            result.update({
                "upload_status": "error",
                "error": error_msg
            })

        return result

    def test_connection(self) -> bool:
        """Проверяет подключение к API"""
        if not self.token:
            logger.error("❌ LARAVEL_TOKEN не установлен")
            return False

        try:
            test_url = f"{self.base_url}/api/v1/ping"  # или другой endpoint для проверки
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/json'
            }

            response = requests.get(test_url, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке подключения: {e}")
            return False

# Глобальный экземпляр uploader
scan_uploader = ScanUploader()
