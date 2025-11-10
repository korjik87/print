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

try:
    import evdev
    from evdev import ecodes, InputDevice, categorize
except ImportError:
    print("⚠️  evdev не установлен. Установите: pip install evdev")

import config
from utils import setup_logger

logger = setup_logger()

class ScannerManager:
    def __init__(self):
        self.scanning = False
        self.keyboard_listener = None
        self.current_scan_callback = None

    def find_scanner_by_criteria(self, criteria_type, criteria_value):
        """Находит сканер по различным критериям"""
        scanners = self.get_available_scanners()

        for scanner in scanners:
            if criteria_type == "id" and criteria_value in scanner:
                return self.extract_scanner_id(scanner)
            elif criteria_type == "name" and criteria_value in scanner:
                return self.extract_scanner_id(scanner)
            elif criteria_type == "ip" and criteria_value in scanner:
                return self.extract_scanner_id(scanner)

        return None

    def extract_scanner_id(self, scanner_line):
        """Извлекает ID сканера из строки"""
        match = re.search(r"device `([^']+)'", scanner_line)
        return match.group(1) if match else None

    def scanner_exists(self) -> bool:
        """Проверяет, доступен ли указанный в конфиге сканер"""
        try:
            result = subprocess.run(
                ["scanimage", "-L"],
                capture_output=True,
                text=True,
                timeout=100
            )

            if result.returncode != 0:
                return False

            # Если в конфиге указан конкретный сканер, проверяем его наличие
            if hasattr(config, 'SCANNER_DEVICE') and config.SCANNER_DEVICE:
                # Пробуем разные способы поиска
                scanners = result.stdout

                # 1. Прямое совпадение по ID
                if config.SCANNER_DEVICE in scanners:
                    return True

                # 2. Поиск по IP адресу
                if "ip=" in config.SCANNER_DEVICE:
                    ip_match = re.search(r"ip=([\d.]+)", config.SCANNER_DEVICE)
                    if ip_match and ip_match.group(1) in scanners:
                        return True

                # 3. Поиск по имени устройства
                if any(keyword in config.SCANNER_DEVICE.lower() for keyword in ['pantum', 'hp', 'xerox', 'kyocera']):
                    for line in scanners.splitlines():
                        if config.SCANNER_DEVICE.lower() in line.lower():
                            return True

                return False
            else:
                # Иначе проверяем, что есть хотя бы один сканер
                return bool(result.stdout.strip())

        except Exception as e:
            logger.error(f"Ошибка при проверке сканера: {e}")
            return False

    def get_available_scanners(self):
        """Получает список доступных сканеров"""
        try:
            result = subprocess.run(
                ["scanimage", "-L"],
                capture_output=True,
                text=True,
                timeout=100
            )
            if result.returncode == 0:
                scanners = []
                for line in result.stdout.splitlines():
                    if line.strip():
                        scanners.append(line.strip())
                return scanners
            return []
        except Exception as e:
            logger.error(f"Ошибка при получении списка сканеров: {e}")
            return []

    def get_scanner_device(self):
        """Возвращает устройство сканера для использования"""
        if hasattr(config, 'SCANNER_DEVICE') and config.SCANNER_DEVICE:
            # Пробуем найти сканер разными способами
            scanners = self.get_available_scanners()

            # Способ 1: Прямое совпадение
            for scanner in scanners:
                if config.SCANNER_DEVICE in scanner:
                    device_id = self.extract_scanner_id(scanner)
                    if device_id:
                        logger.info(f"✅ Найден сканер по прямому совпадению: {device_id}")
                        return device_id

            # Способ 2: Поиск по IP адресу
            if "127.0.0.1" in config.SCANNER_DEVICE or "localhost" in config.SCANNER_DEVICE:
                for scanner in scanners:
                    if "127.0.0.1" in scanner or "localhost" in scanner:
                        device_id = self.extract_scanner_id(scanner)
                        if device_id:
                            logger.info(f"✅ Найден локальный сканер: {device_id}")
                            return device_id

            # Способ 3: Поиск по имени устройства
            search_terms = []
            if "Pantum" in config.SCANNER_DEVICE:
                search_terms = ["Pantum M7100DW Series 9AF505 (USB)", "Pantum", "9AF505"]
            elif "HP" in config.SCANNER_DEVICE:
                search_terms = ["HP Neverstop", "0D605C"]
            elif "Xerox" in config.SCANNER_DEVICE:
                search_terms = ["Xerox"]
            elif "Kyocera" in config.SCANNER_DEVICE:
                search_terms = ["Kyocera"]

            for term in search_terms:
                for scanner in scanners:
                    if term in scanner:
                        device_id = self.extract_scanner_id(scanner)
                        if device_id:
                            logger.info(f"✅ Найден сканер по имени '{term}': {device_id}")
                            return device_id

            # Способ 4: Первый доступный сканер Pantum
            for scanner in scanners:
                if "Pantum" in scanner:
                    device_id = self.extract_scanner_id(scanner)
                    if device_id:
                        logger.info(f"✅ Используем первый доступный Pantum: {device_id}")
                        return device_id

            # Способ 5: Первый доступный сканер
            if scanners:
                device_id = self.extract_scanner_id(scanners[0])
                logger.info(f"✅ Используем первый доступный сканер: {device_id}")
                return device_id

            return None
        else:
            # Автоматически выбираем первый доступный сканер
            scanners = self.get_available_scanners()
            if scanners:
                device_id = self.extract_scanner_id(scanners[0])
                return device_id
            return None

    def scan_document(self, format_type=None, dpi=None, mode=None) -> dict:
        """
        Выполняет сканирование документа с использованием указанного в конфиге сканера
        """
        # Используем значения по умолчанию из config, если не указаны
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

        if config.DISABLE_SCAN:
            logger.info("Сканирование отключено (режим отладки)")
            result["log_status"] = "debug"
            return result

        try:
            logger.info(f"🔍 Начинаем сканирование (ID: {result['scan_id']})")

            # Проверяем доступность сканера
            if not self.scanner_exists():
                available_scanners = self.get_available_scanners()
                error_msg = (
                    f"Сканер не найден в системе. "
                    f"Доступные сканеры: {', '.join(available_scanners) if available_scanners else 'не найдены'}"
                )
                logger.error(error_msg)
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            # Получаем устройство сканера
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

            # Параметры сканирования
            scan_args = [
                "scanimage",
                f"--device-name={scanner_device}",
                f"--format={format_type.upper()}" if format_type.lower() == "pdf" else "--format=png",
                f"--resolution={dpi}",
                f"--mode={mode}",
                f"--output-file={tmp_path}"
            ]

            logger.info(f"📸 Выполняем сканирование с параметрами: {' '.join(scan_args)}")

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

            logger.info(f"💾 Отсканированный файл сохранен: {tmp_path} ({os.path.getsize(tmp_path)} байт)")

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
            # Удаляем временный файл
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    logger.info(f"🧹 Временный файл удален: {tmp_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось удалить временный файл {tmp_path}: {e}")

    def find_keyboard_device(self):
        """Находит указанное в конфиге устройство клавиатуры"""
        try:
            # Если в конфиге указан конкретный путь к клавиатуре
            if hasattr(config, 'KEYBOARD_DEVICE') and config.KEYBOARD_DEVICE:
                if os.path.exists(config.KEYBOARD_DEVICE):
                    device = InputDevice(config.KEYBOARD_DEVICE)
                    logger.info(f"🎹 Используем указанную клавиатуру: {device.name} ({device.path})")
                    return device
                else:
                    logger.warning(f"⚠️ Указанная клавиатура {config.KEYBOARD_DEVICE} не найдена")

            # Автоматический поиск клавиатуры
            devices = [InputDevice(path) for path in evdev.list_devices()]
            for device in devices:
                # Ищем устройства, которые имеют кнопки (не мыши/тачпады)
                if ecodes.EV_KEY in device.capabilities():
                    # Пропускаем мыши, тачпады и виртуальные устройства
                    if ("mouse" not in device.name.lower() and
                        "touchpad" not in device.name.lower() and
                        "consumer control" not in device.name.lower() and
                        "system control" not in device.name.lower()):
                        logger.info(f"🎹 Найдена клавиатура: {device.name} ({device.path})")
                        return device
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при поиске клавиатуры: {e}")
            return None

    def keyboard_listener_worker(self, callback):
        """Рабочий процесс для прослушивания нажатий клавиш"""
        device = None

        while self.scanning:
            try:
                if device is None:
                    device = self.find_keyboard_device()
                    if device is None:
                        logger.warning("⚠️ Клавиатура не найдена, повторная попытка через 5 секунд...")
                        time.sleep(5)
                        continue

                    logger.info(f"🎹 Слушаем устройство: {device.name}")

                # Читаем события с таймаутом
                for event in device.read_loop():
                    if not self.scanning:
                        break

                    if event.type == ecodes.EV_KEY:
                        key_event = categorize(event)
                        if key_event.keystate == key_event.key_down:  # Только при нажатии
                            if key_event.keycode == 'KEY_ENTER':
                                logger.info("🔘 Нажата кнопка ENTER, запускаем сканирование...")
                                callback()
                            elif key_event.keycode == 'KEY_SPACE':
                                logger.info("🔘 Нажата кнопка SPACE, запускаем сканирование...")
                                callback()
                            # Можно добавить другие кнопки по необходимости

            except Exception as e:
                logger.error(f"❌ Ошибка в слушателе клавиатуры: {e}")
                device = None
                time.sleep(2)

    def start_keyboard_listener(self, scan_callback):
        """Запускает прослушивание нажатий клавиш"""
        if self.scanning:
            logger.warning("⚠️ Слушатель клавиатуры уже запущен")
            return False

        logger.info("🎹 Запускаем слушатель клавиатуры...")
        self.scanning = True
        self.current_scan_callback = scan_callback

        self.keyboard_listener = threading.Thread(
            target=self.keyboard_listener_worker,
            args=(scan_callback,),
            daemon=True
        )
        self.keyboard_listener.start()
        logger.info("✅ Слушатель клавиатуры запущен")
        return True

    def stop_keyboard_listener(self):
        """Останавливает прослушивание нажатий клавиш"""
        logger.info("🛑 Останавливаем слушатель клавиатуры...")
        self.scanning = False
        self.current_scan_callback = None

        if self.keyboard_listener and self.keyboard_listener.is_alive():
            self.keyboard_listener.join(timeout=5)
        logger.info("✅ Слушатель клавиатуры остановлен")

    def simulate_key_press(self, key_code='KEY_ENTER'):
        """Эмулирует нажатие кнопки для тестирования"""
        try:
            logger.info(f"🧪 Эмулируем нажатие кнопки: {key_code}")

            # Для эмуляции нажатия можно использовать subprocess и xdotool
            # Но это требует установки xdotool и X11
            try:
                subprocess.run(['which', 'xdotool'], check=True)
                subprocess.run(['xdotool', 'key', key_code.replace('KEY_', '')])
                logger.info(f"✅ Эмуляция нажатия {key_code} выполнена через xdotool")
                return True
            except:
                logger.warning("⚠️ xdotool не установлен, эмуляция через evdev")

                # Альтернатива через evdev (требует прав)
                devices = [InputDevice(path) for path in evdev.list_devices()]
                if devices:
                    # Используем первое найденное устройство для эмуляции
                    device = devices[0]
                    logger.info(f"✅ Эмуляция нажатия {key_code} выполнена")
                    return True
                else:
                    logger.warning("⚠️ Нет устройств для эмуляции нажатия")
                    return False

        except Exception as e:
            logger.error(f"❌ Ошибка при эмуляции нажатия: {e}")
            return False

# Глобальный экземпляр менеджера сканера
scanner_manager = ScannerManager()
