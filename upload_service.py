# upload_service.py
#!/usr/bin/env python3
"""
Сервис загрузки сканов в админку.
Периодически проверяет директорию scans_storage и загружает неотправленные сканы.
"""

import os
import json
import time
import glob
import base64
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List

import config
from utils import setup_logger

# Настройка логирования
logger = setup_logger()

class UploadService:
    def __init__(self, storage_dir="scans_storage", check_interval=30):
        self.storage_dir = storage_dir
        self.check_interval = check_interval
        self.running = False

        # Увеличиваем лимиты
        self.max_attempts = 10
        self.retry_delays = [10, 30, 60, 300, 600, 1200, 1800, 3600, 7200, 14400]

        # Ошибки, которые можно автоматически сбрасывать после исправления
        self.recoverable_errors = ['413', 'Request Entity Too Large', 'Connection', 'Timeout']

        # API настройки
        self.base_url = config.LARAVEL_API.rstrip('/')
        self.token = config.LARAVEL_TOKEN
        self.upload_endpoint = config.SCAN_UPLOAD_ENDPOINT

    def get_pending_scans(self) -> List[Dict]:
        """Получает список сканов, ожидающих загрузки"""
        pending_scans = []

        # Ищем все JSON файлы с метаданными
        pattern = os.path.join(self.storage_dir, "scan_*.json")
        for metadata_file in glob.glob(pattern):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # Проверяем статус и количество попыток
                status = metadata.get('status', 'pending')
                upload_attempts = metadata.get('upload_attempts', 0)
                last_attempt = metadata.get('last_upload_attempt')
                upload_error = metadata.get('upload_error', '')

                # Автоматический сброс для исправленных ошибок
                if status == 'error' and upload_attempts >= self.max_attempts:
                    if any(error in upload_error for error in self.recoverable_errors):
                        logger.info(f"🔄 Автоматический сброс для {metadata['scan_id']} (ошибка: {upload_error[:50]}...)")
                        metadata['status'] = 'pending'
                        metadata['upload_attempts'] = 0
                        metadata['upload_error'] = None
                        metadata['queue_status'] = 'pending'

                        with open(metadata_file, 'w', encoding='utf-8') as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)

                        # Добавляем в обработку
                        pending_scans.append({
                            'metadata': metadata,
                            'metadata_file': metadata_file
                        })
                        continue

                # Пропускаем уже отправленные в очередь сканы
                if status == 'queued':
                    continue

                if status == 'pending' or (status == 'error' and upload_attempts < self.max_attempts):
                    # Проверяем, не рано ли пытаться снова - СОХРАНЯЕМ ЛОГИКУ ЗАДЕРЖЕК
                    if last_attempt:
                        try:
                            last_attempt_time = datetime.fromisoformat(last_attempt)
                            delay_seconds = self.retry_delays[min(upload_attempts, len(self.retry_delays) - 1)]
                            if datetime.now() - last_attempt_time < timedelta(seconds=delay_seconds):
                                continue
                        except ValueError:
                            # Если ошибка в формате даты, игнорируем задержку
                            pass

                    pending_scans.append({
                        'metadata': metadata,
                        'metadata_file': metadata_file
                    })

            except Exception as e:
                logger.error(f"❌ Ошибка чтения метаданных {metadata_file}: {e}")

        return pending_scans

    def upload_scan(self, scan_data: Dict) -> Dict:
        """Отправляет скан на сервер для постановки в очередь RabbitMQ"""
        result = {
            "upload_status": "success",
            "error": None,
            "response_data": None
        }

        try:
            upload_url = f"{self.base_url}{self.upload_endpoint}"

            # Подготавливаем файл для отправки
            scan_file_path = scan_data['file_path']
            if not os.path.exists(scan_file_path):
                raise FileNotFoundError(f"Scan file not found: {scan_file_path}")

            # Читаем содержимое файла ПЕРЕД созданием files
            with open(scan_file_path, 'rb') as f:
                file_content = f.read()

            # Теперь используем прочитанное содержимое
            files = {
                'scan_file': (
                    scan_data['filename'],
                    file_content,  # Используем уже прочитанное содержимое
                    'application/octet-stream'
                )
            }

            data = {
                'scan_id': scan_data['scan_id'],
                'filename': scan_data['filename'],
                'scan_format': 'pdf' if scan_data['filename'].lower().endswith('.pdf') else 'png',
                'scan_dpi': scan_data.get('dpi', config.SCANNER_DPI),
                'scan_mode': scan_data.get('mode', config.SCANNER_MODE),
                'scanner_device': scan_data.get('scanner_device', 'python_uploader'),
                'timestamp': int(time.time()),
                'additional_metadata': scan_data.get('additional_metadata', {})
            }

            headers = {
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/json'
            }

            logger.info(f"📤 Отправка скана {scan_data['scan_id']} в очередь...")

            # СОХРАНЯЕМ ТАЙМАУТЫ И ОБРАБОТКУ ОШИБОК
            response = requests.post(
                upload_url,
                files=files,
                data=data,
                headers=headers,
                timeout=60  # Увеличиваем таймаут для больших файлов
            )

            if response.status_code in [200, 201]:
                response_data = response.json()
                logger.info(f"✅ Скан поставлен в очередь: {scan_data['scan_id']}")
                result["response_data"] = response_data

                # Проверяем, что сервер принял файл
                if 'data' in response_data and 'id' in response_data['data']:
                    result["scan_record_id"] = response_data['data']['id']
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
            error_msg = f"Ошибка при отправке скана: {e}"
            logger.error(f"❌ {error_msg}")
            result.update({
                "upload_status": "error",
                "error": error_msg
            })
        except Exception as e:
            error_msg = f"Неожиданная ошибка при отправке скана: {e}"
            logger.error(f"❌ {error_msg}")
            result.update({
                "upload_status": "error",
                "error": error_msg
            })

        return result

    def process_scan(self, scan_info: Dict):
        """Обрабатывает один скан: отправляет на сервер для постановки в очередь"""
        metadata = scan_info['metadata']
        metadata_file = scan_info['metadata_file']
        scan_id = metadata['scan_id']

        try:
            # Проверяем существование файла скана
            scan_path = metadata['file_path']
            if not os.path.exists(scan_path):
                logger.error(f"❌ Файл скана не найден: {scan_path}")
                self._update_metadata_error(metadata_file, metadata, "Файл скана не найден")
                return

            # Подготавливаем данные для загрузки
            upload_data = {
                'scan_id': scan_id,
                'filename': metadata['original_filename'],
                'file_path': scan_path,
                'dpi': metadata.get('dpi', config.SCANNER_DPI),
                'mode': metadata.get('mode', config.SCANNER_MODE),
                'scanner_device': metadata.get('scanner_device', 'python_uploader'),
                'additional_metadata': {
                    'original_path': scan_path,
                    'file_size': os.path.getsize(scan_path),
                    'upload_service_version': '2.0-queue',
                    'retry_count': metadata.get('upload_attempts', 0)
                }
            }

            # Отправляем скан (теперь он ставится в очередь на S3)
            upload_result = self.upload_scan(upload_data)

            # Обновляем метаданные
            if upload_result['upload_status'] == 'success':
                self._update_metadata_success(metadata_file, metadata, upload_result)
                logger.info(f"✅ Скан {scan_id} поставлен в очередь на загрузку в S3")
            else:
                self._update_metadata_error(metadata_file, metadata, upload_result['error'])
                logger.warning(f"⚠️ Ошибка постановки скана {scan_id} в очередь: {upload_result['error']}")

        except Exception as e:
            error_msg = f"Ошибка обработки скана: {e}"
            logger.error(f"❌ {error_msg}")
            self._update_metadata_error(metadata_file, metadata, error_msg)

    def _update_metadata_success(self, metadata_file: str, metadata: Dict, upload_result: Dict):
        """Обновляет метаданные после успешной отправки в очередь"""
        metadata.update({
            'status': 'queued',  # Статус - файл в очереди
            'uploaded_to_server_at': datetime.now().isoformat(),
            'upload_attempts': metadata.get('upload_attempts', 0) + 1,
            'last_upload_attempt': datetime.now().isoformat(),
            'server_response': upload_result.get('response_data'),
            'scan_record_id': upload_result.get('scan_record_id'),
            'upload_error': None,
            'queue_status': 'waiting'  # Используем существующий queue_status
        })

        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def _update_metadata_error(self, metadata_file: str, metadata: Dict, error: str):
        """Обновляет метаданные после ошибки отправки - СОХРАНЯЕМ ЛОГИКУ"""
        metadata.update({
            'status': 'error',
            'upload_attempts': metadata.get('upload_attempts', 0) + 1,
            'last_upload_attempt': datetime.now().isoformat(),
            'upload_error': error,
            'queue_status': 'error'  # Используем существующий queue_status
        })

        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def run(self):
        """Запускает сервис загрузки"""
        logger.info("🚀 Запуск сервиса загрузки сканов (QUEUE MODE)...")
        logger.info(f"📁 Директория: {self.storage_dir}")
        logger.info(f"⏱️  Интервал проверки: {self.check_interval} сек")
        logger.info(f"🔄 Максимум попыток: {self.max_attempts}")
        logger.info("📨 Режим работы: отправка в очередь RabbitMQ")

        self.running = True

        try:
            while self.running:
                # Получаем сканы для загрузки
                pending_scans = self.get_pending_scans()

                if pending_scans:
                    logger.info(f"📨 Найдено сканов для отправки в очередь: {len(pending_scans)}")

                    for scan_info in pending_scans:
                        self.process_scan(scan_info)

                    logger.info(f"✅ Обработка завершена. Следующая проверка через {self.check_interval} сек")
                else:
                    logger.debug("⏳ Нет сканов для отправки в очередь")

                # Ждем перед следующей проверкой
                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("🛑 Сервис остановлен по запросу пользователя")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка в сервисе загрузки: {e}")
        finally:
            self.running = False

    def stop(self):
        """Останавливает сервис"""
        logger.info("🛑 Остановка сервиса загрузки...")
        self.running = False

def main():
    service = UploadService(check_interval=30)
    service.run()

if __name__ == "__main__":
    main()
