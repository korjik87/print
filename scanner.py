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

    def scanner_exists(self) -> bool:
        """Проверяет, доступен ли указанный в конфиге сканер"""
        try:
            result = subprocess.run(
                ["scanimage", "-L"],
                capture_output=True,
                text=True,
                timeout=50
            )

            if result.returncode != 0:
                return False

            if hasattr(config, 'SCANNER_DEVICE') and config.SCANNER_DEVICE:
                return config.SCANNER_DEVICE in result.stdout
            else:
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
                timeout=50
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
            scanners = self.get_available_scanners()

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
        else:
            scanners = self.get_available_scanners()
            if scanners:
                device_match = re.search(r"device `([^']+)'", scanners[0])
                return device_match.group(1) if device_match else None
            return None

    def scan_document(self, format_type=None, dpi=None, mode=None) -> dict:
        """
        Выполняет сканирование документа
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
                f"--format={format_type.lower()}" if format_type.lower() == "pdf" else "--format=png",
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
        """Находит устройство ввода указанное в конфиге"""
        try:
            # Если в конфиге указан конкретный путь к клавиатуре
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
                        else:
                            logger.warning(f"⚠️ На устройстве нет настроенных кнопок для сканирования")

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

    # Получаем список триггерных кнопок из конфига
    trigger_keys = getattr(config, 'SCAN_TRIGGER_KEYS', [
        'KEY_ENTER',
        'KEY_SPACE',
        'KEY_POWER',
        'KEY_1'  # Добавляем по умолчанию на всякий случай
    ])

    logger.debug(f"🔍 Проверка кнопки {key_name} в списке: {trigger_keys}")

    is_trigger = key_name in trigger_keys
    logger.debug(f"🔍 Результат проверки: {is_trigger}")

    return is_trigger

def keyboard_listener_worker(self, callback):
    """Рабочий процесс для прослушивания нажатий кнопок"""
    device = None

    while self.scanning:
        try:
            if device is None:
                device = self.find_keyboard_device()
                if device is None:
                    logger.warning("⚠️ Устройство ввода не найдено, повторная попытка через 5 секунд...")
                    time.sleep(5)
                    continue

                logger.info(f"🎹 Начинаем отслеживание устройства: {device.name}")

            # Читаем события с устройства
            for event in device.read_loop():
                if not self.scanning:
                    break

                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)

                    # ОТЛАДОЧНЫЙ ВЫВОД: логируем все события клавиш
                    logger.debug(f"🔍 Событие клавиши: {key_event.keycode} (код: {event.code}, состояние: {key_event.keystate})")

                    if key_event.keystate == key_event.key_down:  # Только при нажатии
                        logger.info(f"🔘 Нажата кнопка: {key_event.keycode}")

                        if self.is_trigger_key(key_event):
                            logger.info(f"🎯 ТРИГГЕР! Кнопка {key_event.keycode} в списке триггеров, запускаем сканирование...")
                            callback()
                        else:
                            logger.info(f"❌ Кнопка {key_event.keycode} не в списке триггеров")

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
