#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import re
import threading
import subprocess

# Добавляем текущую директорию в путь Python
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Импортируем наши модули
from scanner import scanner_manager
from scan_uploader import scan_uploader
import config

# Глобальные переменные для evdev (будут установлены при необходимости)
ecodes = None
categorize = None
InputDevice = None

def setup_evdev():
    """Настраивает evdev модуль если доступен"""
    global ecodes, categorize, InputDevice
    try:
        from evdev import ecodes, InputDevice, categorize
        return True
    except ImportError:
        print("⚠️  Модуль evdev не установлен. Установите: pip install evdev")
        return False



class ScannerApp:
    def __init__(self):
        self.is_running = False
        self.test_mode = False

    def on_scan_triggered(self):
        """Callback функция, вызываемая при нажатии кнопки сканирования"""
        print("🎯 Запуск сканирования по нажатию кнопки...")
        
        # Выполняем сканирование
        scan_result = scanner_manager.scan_document()
        
        if scan_result['status'] == 'success':
            print(f"✅ Сканирование завершено! ID: {scan_result['scan_id']}")
            print(f"📁 Файл: {scan_result['filename']}")
            print(f"📊 Размер данных: {len(scan_result['content'])} символов base64")
            
            # Отправляем скан в админку
            upload_result = self.upload_scan_to_server(scan_result)

            # Обрабатываем результат
            self.handle_scan_result(scan_result, upload_result)
        else:
            print(f"❌ Ошибка сканирования: {scan_result['error']}")
    
    def upload_scan_to_server(self, scan_result):
        """Отправляет скан на сервер Laravel"""
        print("📤 Отправка скана в админку...")
        return scan_uploader.upload_scan(scan_result)

    def handle_scan_result(self, scan_result, upload_result):
        """Обработка результатов сканирования и отправки"""
        # Сохраняем полные метаданные
        output_data = {
            'scan_id': scan_result['scan_id'],
            'timestamp': time.time(),
            'filename': scan_result['filename'],
            'content_length': len(scan_result['content']),
            'scan_status': scan_result['status'],
            'upload_status': upload_result['upload_status'],
            'upload_error': upload_result['error'],
            'response_data': upload_result.get('response_data')
        }

        # Сохраняем метаданные в файл
        metadata_file = f"scan_{scan_result['scan_id']}.json"
        with open(metadata_file, 'w') as f:
            json.dump(output_data, f, indent=2)

        print(f"💾 Метаданные сохранены в {metadata_file}")

        # Выводим результат отправки
        if upload_result['upload_status'] == 'success':
            print("✅ Скан успешно отправлен в админку")
            if upload_result.get('response_data'):
                print(f"📋 Ответ сервера: {upload_result['response_data']}")
        else:
            print(f"❌ Ошибка отправки: {upload_result['error']}")

            # Сохраняем скан локально для последующей отправки
            if scan_result.get('content'):
                backup_file = f"scan_backup_{scan_result['scan_id']}.{'pdf' if scan_result['filename'].endswith('.pdf') else 'png'}"
                with open(backup_file, 'w') as f:
                    f.write(scan_result['content'])
                print(f"💾 Скан сохранен локально в {backup_file} для последующей отправки")
    
    def signal_handler(self, sig, frame):
        """Обработчик сигналов для graceful shutdown"""
        print(f"\n🛑 Получен сигнал {sig}, останавливаемся...")
        self.stop()
    
    def simulate_scan_trigger(self):
        """Эмулирует нажатие кнопки сканирования"""
        print("🧪 Эмулируем нажатие кнопки сканирования...")
        self.on_scan_triggered()

    def test_api_connection(self):
        """Тестирует подключение к API"""
        print("\n🔌 Тестируем подключение к Laravel API...")

        if not config.LARAVEL_TOKEN:
            print("❌ LARAVEL_TOKEN не установлен в конфигурации")
            return False

        if not config.LARAVEL_API or config.LARAVEL_API == "http://localhost":
            print("❌ LARAVEL_API не настроен правильно")
            return False

        print(f"🌐 API: {config.LARAVEL_API}")
        print(f"🔑 Токен: {config.LARAVEL_TOKEN[:10]}...")  # Показываем только начало токена

        if scan_uploader.test_connection():
            print("✅ Подключение к API успешно")
            return True
        else:
            print("❌ Не удалось подключиться к API")
            return False

    def test_scanner_connection(self):
        """Тестирует подключение к сканеру"""
        print("\n🧪 Тестируем подключение к сканеру...")

        scanner_device = scanner_manager.get_scanner_device()
        if not scanner_device:
            print("❌ Не удалось определить устройство сканера")
            return False

        print(f"📋 Определено устройство: {scanner_device}")

        # Пробуем получить информацию о сканере
        try:
            result = subprocess.run(
                ["scanimage", "--device-name", scanner_device, "--help"],
                capture_output=True,
                text=True,
                timeout=50
            )

            if result.returncode == 0:
                print("✅ Сканер отвечает на запросы")
                return True
            else:
                print(f"❌ Сканер не отвечает: {result.stderr}")
                return False

        except Exception as e:
            print(f"❌ Ошибка тестирования сканера: {e}")
            return False

    def detect_devices(self):
        """Обнаружение и вывод информации об устройствах"""
        print("🔍 Обнаружение устройств...")

        # Сканеры
        print("\n📷 Сканеры:")
        scanners = scanner_manager.get_available_scanners()
        if scanners:
            for i, scanner in enumerate(scanners):
                print(f"  {i+1}. {scanner}")

                # Извлекаем ID устройства
                device_match = re.search(r"device `([^']+)'", scanner)
                if device_match:
                    device_id = device_match.group(1)
                    print(f"     ID: {device_id}")

                    # Проверяем, используется ли этот сканер в конфиге
                    if hasattr(config, 'SCANNER_DEVICE') and config.SCANNER_DEVICE:
                        if config.SCANNER_DEVICE in scanner:
                            print(f"     ✅ Совпадение с конфигом")
                        elif "127.0.0.1" in config.SCANNER_DEVICE and "127.0.0.1" in scanner:
                            print(f"     ✅ Совпадение по IP 127.0.0.1")
                        elif config.SCANNER_DEVICE.lower() in scanner.lower():
                            print(f"     ✅ Частичное совпадение с конфигом")
        else:
            print("  ❌ Сканеры не найдены")
            print("  💡 Установите SANE: sudo apt-get install sane sane-utils")

        # Клавиатуры
        print("\n🎹 Устройства ввода:")
        try:
            import evdev
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
            keyboards = []

            for device in devices:
                if evdev.ecodes.EV_KEY in device.capabilities():
                    # Фильтруем только клавиатуры
                    if ("mouse" not in device.name.lower() and
                        "touchpad" not in device.name.lower() and
                        "consumer control" not in device.name.lower() and
                        "system control" not in device.name.lower()):
                        keyboards.append(device)

            for i, keyboard in enumerate(keyboards):
                print(f"  {i+1}. {keyboard.name}")
                print(f"     Путь: {keyboard.path}")

                # Проверяем, используется ли эта клавиатура в конфиге
                if hasattr(config, 'KEYBOARD_DEVICE') and config.KEYBOARD_DEVICE == keyboard.path:
                    print(f"     ✅ Используется в конфиге")

            if not keyboards:
                print("  ❌ Клавиатуры не найдены")

        except ImportError:
            print("  ❌ Модуль evdev не установлен")
        except Exception as e:
            print(f"  ❌ Ошибка при обнаружении клавиатур: {e}")

    def interactive_menu(self):
        """Интерактивное меню для тестирования"""
        while True:
            print("\n" + "="*50)
            print("🎮 МЕНЮ ТЕСТИРОВАНИЯ СКАНЕРА")
            print("="*50)
            print("1. 🧪 Эмуляция нажатия кнопки (запуск сканирования)")
            print("2. 🔍 Проверить доступность сканера")
            print("3. 🌐 Проверить подключение к API")
            print("4. 🎹 Проверить клавиатуру")
            print("5. 🚀 Запуск службы сканирования (ожидание кнопки)")
            print("6. 🛑 Выход")
            print("="*50)

            choice = input("Выберите действие (1-6): ").strip()

            if choice == "1":
                self.simulate_scan_trigger()
            elif choice == "2":
                self.test_scanner_manual()
            elif choice == "3":
                self.test_api_connection()
            elif choice == "4":
                self.test_keyboard_manual()
            elif choice == "5":
                print("🚀 Запускаем службу сканирования...")
                self.start_service()
                break
            elif choice == "6":
                print("👋 Выход...")
                break
            else:
                print("❌ Неверный выбор. Попробуйте снова.")

    def test_scanner_manual(self):
        """Ручное тестирование сканера"""
        print("\n🔍 Ручное тестирование сканера...")

        # Получаем устройство сканера
        scanner_device = scanner_manager.get_scanner_device()
        if not scanner_device:
            print("❌ Не удалось определить устройство сканера")
            return

        print(f"📋 Используем сканер: {scanner_device}")

        # Тестируем простую команду
        try:
            result = subprocess.run(
                ["scanimage", "--device-name", scanner_device, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                print("✅ Команда scanimage выполнена успешно")
                print(f"📄 Вывод: {result.stdout.strip()}")
            else:
                print(f"❌ Ошибка: {result.stderr}")

        except Exception as e:
            print(f"❌ Ошибка выполнения команды: {e}")

    def test_keyboard_manual(self):
        """Ручное тестирование клавиатуры"""
        print("\n🎹 Ручное тестирование клавиатуры...")

        # Настраиваем evdev
        if not setup_evdev():
            print("❌ Модуль evdev не установлен. Установите: pip install evdev")
            return

        keyboard_device = scanner_manager.find_keyboard_device()
        if keyboard_device:
            print(f"✅ Клавиатура найдена: {keyboard_device.name}")
            print(f"📍 Путь: {keyboard_device.path}")

            # Тестируем чтение событий в реальном времени
            print("\n🎯 Тестируем события клавиатуры...")
            print("   Нажмите любую клавишу на клавиатуре (для выхода нажмите ESC)")
            print("   Или нажмите Ctrl+C для выхода")

            try:
                for event in keyboard_device.read_loop():
                    # Обрабатываем только события клавиш
                    if event.type == ecodes.EV_KEY:
                        key_event = categorize(event)

                        # Определяем состояние клавиши
                        if event.value == 0:
                            state = "отпущена"
                        elif event.value == 1:
                            state = "нажата"
                        elif event.value == 2:
                            state = "удерживается"
                        else:
                            state = f"неизвестно ({event.value})"

                        print(f"   🔘 Клавиша: {key_event.keycode} (код: {event.code}), состояние: {state}")

                        # Выход по ESC (только при нажатии или удерживании)
                        if key_event.keycode == 'KEY_ESC' and event.value in [1, 2]:
                            print("   🛑 Выход из теста клавиатуры")
                            break
            except KeyboardInterrupt:
                print("\n   🛑 Прервано пользователем")
        else:
            print("❌ Клавиатура не найдена")

    def start_service(self):
        """Запуск службы сканирования"""
        print("🚀 Запуск сервиса сканирования...")
        
        # Проверяем подключение к API
        if not self.test_api_connection():
            print("❌ Не удалось подключиться к API. Продолжаем без отправки сканов.")

        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.is_running = True

        # Проверяем доступность сканера
        print("\n🔍 Проверяем доступность сканера...")
        if scanner_manager.scanner_exists():
            scanner_device = scanner_manager.get_scanner_device()
            print(f"✅ Сканер доступен: {scanner_device}")
        else:
            print("❌ Указанный сканер не найден")
            return
        
        # Запускаем слушатель клавиатуры
        print("\n🎹 Настройка клавиатуры...")
        if scanner_manager.start_keyboard_listener(self.on_scan_triggered):
            keyboard_device = scanner_manager.find_keyboard_device()
            if keyboard_device:
                print(f"✅ Слушатель клавиатуры запущен: {keyboard_device.name}")
            else:
                print("✅ Слушатель клавиатуры запущен (устройство по умолчанию)")

            print("🎹 Нажимайте ENTER или SPACE для запуска сканирования")
            print("⏹️  Нажмите Ctrl+C для остановки")
        else:
            print("❌ Не удалось запустить слушатель клавиатуры")
            return
        
        try:
            # Главный цикл
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Получен сигнал остановки...")
        finally:
            self.stop()
    
    def start(self):
        """Запуск приложения с интерактивным меню"""
        print("🚀 Запуск сервиса принтера и сканера...")

        # Показываем информацию об устройствах
        self.detect_devices()

        # Запускаем интерактивное меню
        self.interactive_menu()

    def stop(self):
        """Остановка приложения"""
        print("🛑 Останавливаем сервис...")
        self.is_running = False
        scanner_manager.stop_keyboard_listener()
        print("✅ Сервис остановлен")

# Запуск приложения
if __name__ == "__main__":
    app = ScannerApp()

    # Проверяем аргументы командной строки
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            print("🧪 Режим тестирования - эмуляция нажатия кнопки")
            app.simulate_scan_trigger()
        elif sys.argv[1] == "--service":
            print("🚀 Запуск в режиме службы")
            app.start_service()
        else:
            print("❌ Неизвестный аргумент")
            print("Доступные аргументы:")
            print("  --test     - однократный тест сканирования")
            print("  --service  - запуск службы")
            print("  без аргументов - интерактивный режим")
    else:
        # Интерактивный режим по умолчанию
        app.start()
