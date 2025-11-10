#!/usr/bin/env python3
import os
import sys
import time
import json
import signal

# Добавляем текущую директорию в путь Python
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from scanner import scanner_manager

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
    
    def start(self):
        """Запуск приложения"""
        print("🚀 Запуск сервиса принтера и сканера...")
        
        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.is_running = True
        
        # Проверяем доступность сканера
        print("🔍 Проверяем доступность сканера...")
        if scanner_manager.scanner_exists():
            print("✅ Сканер доступен")
            scanners = scanner_manager.get_available_scanners()
            if scanners:
                print("📋 Доступные сканеры:")
                for scanner in scanners:
                    print(f"   - {scanner}")
        else:
            print("❌ Сканер не найден")
            print("💡 Убедитесь что:")
            print("   - Сканер подключен и включен")
            print("   - Установлены драйверы SANE: sudo apt-get install sane sane-utils")
            print("   - Выполните: scanimage -L для проверки")
            return
        
        # Запускаем слушатель клавиатуры
        if scanner_manager.start_keyboard_listener(self.on_scan_triggered):
            print("✅ Слушатель клавиатуры запущен")
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
