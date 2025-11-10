#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import re
import subprocess

# Добавляем текущую директорию в путь Python
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from scanner import scanner_manager
import config

class ScannerApp:
    def __init__(self):
        self.is_running = False
    
    def on_scan_triggered(self):
        """Callback функция, вызываемая при нажатии кнопки сканирования"""
        print("🎯 Запуск сканирования по нажатию кнопки...")
        
        # Выполняем сканирование
        scan_result = scanner_manager.scan_document()
        
        if scan_result['status'] == 'success':
            print(f"✅ Сканирование завершено! ID: {scan_result['scan_id']}")
            print(f"📁 Файл: {scan_result['filename']}")
            print(f"📊 Размер данных: {len(scan_result['content'])} символов base64")
            
            # Здесь можно отправить результат на сервер, сохранить в БД и т.д.
            self.handle_scan_result(scan_result)
        else:
            print(f"❌ Ошибка сканирования: {scan_result['error']}")
    
    def handle_scan_result(self, scan_result):
        """Обработка результатов сканирования"""
        # Пример: сохранение метаданных в файл
        output_data = {
            'scan_id': scan_result['scan_id'],
            'timestamp': time.time(),
            'filename': scan_result['filename'],
            'content_length': len(scan_result['content']),
            'status': scan_result['status']
        }
        
        with open(f"scan_{scan_result['scan_id']}.json", 'w') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"💾 Метаданные сканирования сохранены в scan_{scan_result['scan_id']}.json")
    
    def signal_handler(self, sig, frame):
        """Обработчик сигналов для graceful shutdown"""
        print(f"\n🛑 Получен сигнал {sig}, останавливаемся...")
        self.stop()
    
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
                timeout=10
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

    def start(self):
        """Запуск приложения"""
        print("🚀 Запуск сервиса принтера и сканера...")
        
        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.is_running = True
        
        # Показываем информацию об устройствах
        self.detect_devices()

        # Проверяем доступность сканера
        print("\n🔍 Проверяем доступность сканера...")
        if scanner_manager.scanner_exists():
            scanner_device = scanner_manager.get_scanner_device()
            print(f"✅ Сканер доступен: {scanner_device}")

            # Тестируем подключение
            if not self.test_scanner_connection():
                print("❌ Проблемы с подключением к сканеру")
                return
        else:
            print("❌ Указанный сканер не найден")
            available_scanners = scanner_manager.get_available_scanners()
            if available_scanners:
                print("💡 Доступные сканеры:")
                for scanner in available_scanners:
                    print(f"   - {scanner}")
            else:
                print("💡 Сканеры не найдены. Проверьте:")
                print("   - Подключение сканера")
                print("   - Драйверы SANE: sudo apt-get install sane sane-utils")
                print("   - Команду: scanimage -L")
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
    
    def stop(self):
        """Остановка приложения"""
        print("🛑 Останавливаем сервис...")
        self.is_running = False
        scanner_manager.stop_keyboard_listener()
        print("✅ Сервис остановлен")

# Запуск приложения
if __name__ == "__main__":
    app = ScannerApp()
    app.start()
