import subprocess
import tempfile
import os
import base64
import uuid
import time
import select
import threading
import logging
import re
import json
from datetime import datetime

try:
    import evdev
    from evdev import ecodes, InputDevice, categorize
except ImportError:
    print("⚠️  evdev не установлен. Установите: pip install evdev")

import config
from utils import setup_logger

logger = setup_logger()

class ScanStorage:
    def __init__(self, storage_dir="scans_storage"):
        self.storage_dir = storage_dir
        self._ensure_storage_dir()

    def _ensure_storage_dir(self):
        """Создает директорию для хранения сканов, если она не существует"""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)
            # Создаем .gitignore чтобы не отслеживать сканы в git
            gitignore_path = os.path.join(self.storage_dir, ".gitignore")
            with open(gitignore_path, "w") as f:
                f.write("# Автоматически сгенерированные сканы\n")
                f.write("*.pdf\n")
                f.write("*.png\n")
                f.write("*.json\n")
                f.write("!README.md\n")
            logger.info(f"📁 Создана директория для хранения сканов: {self.storage_dir}")

    def save_scan(self, scan_result: dict) -> dict:
        """
        Сохраняет скан в директорию storage_dir
        Возвращает информацию о сохраненном файле
        """
        try:
            scan_id = scan_result["scan_id"]

            # Сохраняем файл скана
            file_extension = "pdf" if scan_result['filename'].endswith('.pdf') else 'png'
            scan_filename = f"scan_{scan_id}.{file_extension}"
            scan_path = os.path.join(self.storage_dir, scan_filename)

            # Декодируем base64 и сохраняем файл
            with open(scan_path, "wb") as f:
                file_content = base64.b64decode(scan_result["content"])
                f.write(file_content)

            # Сохраняем метаданные
            metadata = {
                "scan_id": scan_id,
                "filename": scan_filename,
                "original_filename": scan_result["filename"],
                "file_path": scan_path,
                "file_size": os.path.getsize(scan_path),
                "format": file_extension,
                "dpi": getattr(config, 'SCANNER_DPI', 300),
                "mode": getattr(config, 'SCANNER_MODE', 'Color'),
                "created_at": datetime.now().isoformat(),
                "status": "pending",  # pending, uploaded, error
                "upload_attempts": 0,
                "last_upload_attempt": None,
                "upload_error": None
            }

            metadata_filename = f"scan_{scan_id}.json"
            metadata_path = os.path.join(self.storage_dir, metadata_filename)

            with open(metadata_path, "w", encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(f"💾 Скан сохранен: {scan_path} ({metadata['file_size']} байт)")

            return {
                "status": "success",
                "scan_id": scan_id,
                "scan_path": scan_path,
                "metadata_path": metadata_path,
                "metadata": metadata
            }

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения скана: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

class ScannerManager:
    def __init__(self):
        self.scanning = False
        self.keyboard_listener = None
        self.current_scan_callback = None

        # Защита от множественного запуска
        self.scan_in_progress = False
        self.last_scan_time = 0
        self.scan_cooldown = 3

        # Хранилище сканов
        self.storage = ScanStorage()

        # Кеш для данных сканера
        self._scanner_cache = None
        self._scanner_cache_time = 0
        self._scanner_cache_ttl = 900

        # Кеш для доступных сканеров
        self._available_scanners_cache = None
        self._available_scanners_cache_time = 0

    def _get_scanner_cache(self):
        """Получает кешированные данные сканера, если они еще актуальны"""
        if (self._scanner_cache and
            time.time() - self._scanner_cache_time < self._scanner_cache_ttl):
            return self._scanner_cache
        return None

    def _set_scanner_cache(self, value):
        """Устанавливает кеш сканера"""
        self._scanner_cache = value
        self._scanner_cache_time = time.time()

    def can_start_scan(self):
        """Проверяет, можно ли начать новое сканирование"""
        if self.scan_in_progress:
            logger.debug("⏳ Сканирование уже выполняется, пропускаем")
            return False

        current_time = time.time()
        if current_time - self.last_scan_time < self.scan_cooldown:
            logger.debug("⏳ Сканирование было недавно, пропускаем")
            return False

        return True

    def scanner_exists(self) -> bool:
        """Проверяет, доступен ли указанный в конфиге сканер (с кешированием)"""
        cached_result = self._get_scanner_cache()
        if cached_result is not None:
            logger.debug("✅ Используем кешированные данные сканера")
            return cached_result

        try:
            result = subprocess.run(
                ["scanimage", "-L"],
                capture_output=True,
                text=True,
                timeout=50
            )

            scanner_available = False
            if result.returncode == 0:
                if hasattr(config, 'SCANNER_DEVICE') and config.SCANNER_DEVICE:
                    scanner_available = config.SCANNER_DEVICE in result.stdout
                else:
                    scanner_available = bool(result.stdout.strip())

            # Кешируем результат
            self._set_scanner_cache(scanner_available)

            if scanner_available:
                logger.info("✅ Сканер доступен (данные закешированы)")
            else:
                logger.warning("❌ Сканер недоступен")

            return scanner_available

        except subprocess.TimeoutExpired:
            logger.error("❌ Таймаут при проверке сканера")
            # Не кешируем при ошибке таймаута
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке сканера: {e}")
            return False

    def get_available_scanners(self):
        """Получает список доступных сканеров (с кешированием)"""
        # Используем кеш, если он есть и не старше 5 минут
        if (self._available_scanners_cache and
            time.time() - self._available_scanners_cache_time < 300):
            logger.debug("✅ Используем кешированный список сканеров")
            return self._available_scanners_cache

        try:
            result = subprocess.run(
                ["scanimage", "-L"],
                capture_output=True,
                text=True,
                timeout=50
            )

            scanners = []
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.strip():
                        scanners.append(line.strip())

            # Кешируем результат
            self._available_scanners_cache = scanners
            self._available_scanners_cache_time = time.time()

            logger.info(f"✅ Получен список сканеров ({len(scanners)} шт.), данные закешированы")
            return scanners

        except subprocess.TimeoutExpired:
            logger.error("❌ Таймаут при получении списка сканеров")
            # Возвращаем кеш, даже если старый, при таймауте
            return self._available_scanners_cache or []
        except Exception as e:
            logger.error(f"❌ Ошибка при получении списка сканеров: {e}")
            return self._available_scanners_cache or []

    def get_scanner_device(self):
        """Возвращает устройство сканера для использования (с кешированием)"""
        # Используем кешированные данные о доступности
        if not self.scanner_exists():
            return None

        scanners = self.get_available_scanners()
        if not scanners:
            return None

        if hasattr(config, 'SCANNER_DEVICE') and config.SCANNER_DEVICE:
            # Ищем точное совпадение
            for scanner in scanners:
                if config.SCANNER_DEVICE in scanner:
                    device_match = re.search(r"device `([^']+)'", scanner)
                    if device_match:
                        device_id = device_match.group(1)
                        logger.info(f"✅ Найден сканер: {device_id}")
                        return device_id

        # Если точного совпадения нет, используем первый доступный
        if scanners:
            device_match = re.search(r"device `([^']+)'", scanners[0])
            if device_match:
                device_id = device_match.group(1)
                logger.info(f"✅ Используем первый доступный сканер: {device_id}")
                return device_id

        return None

    def scan_document(self, format_type=None, dpi=None, mode=None, use_adf=False) -> dict:
        """
        Выполняет сканирование документа с опциональной поддержкой автоподатчика
        """
        if format_type is None:
            format_type = config.SCANNER_FORMAT
        if dpi is None:
            dpi = config.SCANNER_DPI
        if mode is None:
            mode = config.SCANNER_MODE

        result = {
            "scan_id": str(uuid.uuid4()),
            "status": "success",
            "error": None,
            "content": None,
            "filename": None
        }

        if getattr(config, 'DISABLE_SCAN', False):
            logger.info("Сканирование отключено (режим отладки)")
            result["log_status"] = "debug"
            return result

        # Устанавливаем флаг выполнения сканирования
        self.scan_in_progress = True
        self.last_scan_time = time.time()

        try:
            logger.info(f"🔍 Начинаем сканирование (ID: {result['scan_id']})")
            if use_adf:
                logger.info("📄 Используем автоподатчик документов")

            # Проверяем доступность сканера (использует кеш)
            if not self.scanner_exists():
                available_scanners = self.get_available_scanners()
                error_msg = (
                    f"Сканер не найден в системе. "
                    f"Доступные сканеры: {len(available_scanners)}"
                )
                logger.error(error_msg)
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            # Получаем устройство сканера (использует кеш)
            scanner_device = self.get_scanner_device()
            if not scanner_device:
                error_msg = "Не удалось определить устройство сканера"
                logger.error(error_msg)
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            logger.info(f"🎯 Используем сканер: {scanner_device}")

            # Создаем временный файл для сканирования
            file_extension = "pdf" if format_type.lower() == "pdf" else "png"
            filename = f"scan_{result['scan_id']}.{file_extension}"
            tmp_path = os.path.join(tempfile.gettempdir(), filename)

            # Базовые параметры сканирования
            scan_args = [
                "scanimage",
                f"--device-name={scanner_device}",
                f"--format={format_type.lower()}" if format_type.lower() == "pdf" else "--format=png",
                f"--resolution={dpi}",
                f"--mode={mode}",
                f"--output-file={tmp_path}"
            ]

            # Добавляем опции автоподатчика если включено и настроено
            if use_adf and hasattr(config, 'SCANNER_ADF_OPTIONS'):
                scan_args.extend(config.SCANNER_ADF_OPTIONS)
                logger.info(f"🔧 Используем опции автоподатчика: {config.SCANNER_ADF_OPTIONS}")

            logger.info(f"📸 Выполняем сканирование...")
            logger.debug(f"Параметры: {' '.join(scan_args)}")

            # Выполняем сканирование
            scan_result = subprocess.run(
                scan_args,
                capture_output=True,
                text=True,
                timeout=120  # 2 минуты на сканирование
            )

            if scan_result.returncode != 0:
                error_msg = scan_result.stderr.strip()
                logger.error(f"❌ Ошибка сканирования: {error_msg}")
                result.update({
                    "status": "error",
                    "error": f"Ошибка сканирования: {error_msg}"
                })
                return result

            # Проверяем, что файл создан и не пустой
            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                error_msg = "Сканирование завершилось, но файл не создан или пустой"
                logger.error(f"❌ {error_msg}")
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            file_size = os.path.getsize(tmp_path)
            logger.info(f"💾 Отсканированный файл сохранен: {tmp_path} ({file_size} байт)")

            # Читаем файл и кодируем в base64
            with open(tmp_path, "rb") as f:
                file_content = f.read()
                result["content"] = base64.b64encode(file_content).decode('utf-8')
                result["filename"] = filename

            logger.info(f"✅ Сканирование {result['scan_id']} успешно завершено")
            return result

        except subprocess.TimeoutExpired:
            error_msg = "Таймаут сканирования"
            logger.error(f"❌ {error_msg}")
            result.update({
                "status": "error",
                "error": error_msg
            })
            return result
        except Exception as e:
            error_msg = f"Критическая ошибка сканирования: {str(e)}"
            logger.error(f"❌ {error_msg}")
            result.update({
                "status": "error",
                "error": error_msg
            })
            return result
        finally:
            # Сбрасываем флаг выполнения сканирования
            self.scan_in_progress = False

            # Удаляем временный файл
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    logger.debug(f"🧹 Временный файл удален: {tmp_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось удалить временный файл {tmp_path}: {e}")

    def find_keyboard_device(self):
        """Находит устройство ввода указанное в конфиге"""
        try:
            if hasattr(config, 'KEYBOARD_DEVICE') and config.KEYBOARD_DEVICE:
                if os.path.exists(config.KEYBOARD_DEVICE):
                    device = InputDevice(config.KEYBOARD_DEVICE)
                    logger.info(f"🎹 Используем устройство: {device.name} ({device.path})")

                    # Проверяем доступные кнопки
                    caps = device.capabilities()
                    if ecodes.EV_KEY in caps:
                        keys = caps[ecodes.EV_KEY]
                        available_trigger_keys = []
                        for key_name in getattr(config, 'SCAN_TRIGGER_KEYS', []):
                            key_code = getattr(ecodes, key_name, None)
                            if key_code and key_code in keys:
                                available_trigger_keys.append(key_name)

                        if available_trigger_keys:
                            logger.info(f"🎯 Доступные кнопки для сканирования: {', '.join(available_trigger_keys)}")

                    return device
                else:
                    logger.warning(f"⚠️ Устройство {config.KEYBOARD_DEVICE} не найдено")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при поиске устройства: {e}")
            return None

    def is_trigger_key(self, key_event):
        """Проверяет, является ли нажатая кнопка триггером для сканирования"""
        key_name = key_event.keycode
        trigger_keys = getattr(config, 'SCAN_TRIGGER_KEYS', [
            'KEY_ENTER', 'KEY_SPACE', 'KEY_POWER', 'KEY_1'
        ])

        is_trigger = key_name in trigger_keys
        logger.debug(f"🔍 Проверка кнопки {key_name}: {'триггер' if is_trigger else 'не триггер'}")

        return is_trigger

    def keyboard_listener_worker(self, callback):
        """Рабочий процесс для прослушивания нажатий кнопок"""
        device = None

        logger.info("🎹 Запускаем рабочий процесс слушателя клавиатуры...")

        while self.scanning:
            try:
                if device is None:
                    device = self.find_keyboard_device()
                    if device is None:
                        logger.warning("⚠️ Устройство ввода не найдено, повторная попытка через 5 секунд...")
                        time.sleep(5)
                        continue

                    logger.info(f"🎹 Устройство найдено: {device.name}")

                # Читаем события с устройства
                for event in device.read_loop():
                    if not self.scanning:
                        logger.info("🛑 Слушатель остановлен")
                        break

                    # Обрабатываем только события клавиш
                    if event.type == ecodes.EV_KEY:
                        try:
                            key_event = categorize(event)
                            key_name = key_event.keycode

                            # Обрабатываем как нажатия (1), так и удерживания (2)
                            if event.value in [1, 2]:
                                logger.info(f"🔘 Нажата кнопка: {key_name}")

                                if self.is_trigger_key(key_event):
                                    # Проверяем, можно ли начать сканирование
                                    if self.can_start_scan():
                                        logger.info(f"🎯 ТРИГГЕР! Запускаем сканирование")
                                        callback()
                                    else:
                                        logger.debug("⏳ Сканирование уже выполняется или недавно было, пропускаем")
                                else:
                                    logger.debug(f"❌ Кнопка {key_name} не в списке триггеров")

                        except Exception as e:
                            logger.error(f"❌ Ошибка обработки события клавиши: {e}")

            except Exception as e:
                logger.error(f"❌ Ошибка в слушателе устройства: {e}")
                device = None
                time.sleep(2)

    def start_keyboard_listener(self, scan_callback):
        """Запускает прослушивание нажатий кнопок"""
        if self.scanning:
            logger.warning("⚠️ Слушатель уже запущен")
            return False

        logger.info("🎹 Запускаем слушатель устройства ввода...")
        self.scanning = True
        self.current_scan_callback = scan_callback

        self.keyboard_listener = threading.Thread(
            target=self.keyboard_listener_worker,
            args=(scan_callback,),
            daemon=True
        )
        self.keyboard_listener.start()
        logger.info("✅ Слушатель устройства запущен")
        return True

    def stop_keyboard_listener(self):
        """Останавливает прослушивание нажатий кнопок"""
        logger.info("🛑 Останавливаем слушатель устройства...")
        self.scanning = False
        self.current_scan_callback = None

        if self.keyboard_listener and self.keyboard_listener.is_alive():
            self.keyboard_listener.join(timeout=5)
        logger.info("✅ Слушатель устройства остановлен")

# Глобальный экземпляр менеджера сканера
scanner_manager = ScannerManager()
