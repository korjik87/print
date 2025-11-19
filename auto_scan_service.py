#!/usr/bin/env python3
"""
Автоматическая служба сканирования с поддержкой автоподатчика
Запускает сканирование по нажатию кнопки и отправляет файлы на сервер
"""

import os
import sys
import time
import signal
import logging

# Добавляем текущую директорию в путь Python
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from evdev import ecodes, InputDevice, categorize
except ImportError:
    print("❌ Модуль evdev не установлен. Установите: pip install evdev")
    sys.exit(1)

from scanner import scanner_manager
from scan_uploader import scan_uploader
import config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('auto_scan_service.log')
    ]
)
logger = logging.getLogger(__name__)

class AutoScanService:
    def __init__(self):
        self.is_running = False
        self.scanning_in_progress = False
        self.use_adf = getattr(config, 'USE_AUTOMATIC_DOCUMENT_FEEDER', True)

    def on_scan_triggered(self):
        """Callback функция, вызываемая при нажатии кнопки сканирования"""
        if self.scanning_in_progress:
            logger.info("⏳ Сканирование уже выполняется, пропускаем...")
            return

        self.scanning_in_progress = True
        try:
            if self.use_adf:
                logger.info("🎯 Запуск сканирования с автоподатчиком по нажатию кнопки...")
            else:
                logger.info("🎯 Запуск сканирования по нажатию кнопки...")

            # Выполняем сканирование с опцией автоподатчика
            scan_result = scanner_manager.scan_document(use_adf=self.use_adf)

            if scan_result['status'] == 'success':
                logger.info(f"✅ Сканирование завершено! ID: {scan_result['scan_id']}")
                logger.info(f"📁 Файл: {scan_result['filename']}")
                logger.info(f"📊 Размер данных: {len(scan_result['content'])} символов base64")

                # Отправляем скан в админку
                upload_result = self.upload_scan_to_server(scan_result)

                # Обрабатываем результат
                self.handle_scan_result(scan_result, upload_result)
            else:
                logger.error(f"❌ Ошибка сканирования: {scan_result['error']}")

        except Exception as e:
            logger.error(f"❌ Критическая ошибка при сканировании: {e}")
        finally:
            self.scanning_in_progress = False

    def upload_scan_to_server(self, scan_result):
        """Отправляет скан на сервер Laravel"""
        logger.info("📤 Отправка скана в админку...")
        return scan_uploader.upload_scan(scan_result)

    def handle_scan_result(self, scan_result, upload_result):
        """Обработка результатов сканирования и отправки"""
        if upload_result['upload_status'] == 'success':
            logger.info("✅ Скан успешно отправлен в админку")
            if upload_result.get('response_data'):
                logger.info(f"📋 Ответ сервера: {upload_result['response_data']}")
        else:
            logger.error(f"❌ Ошибка отправки: {upload_result['error']}")

            # Сохраняем скан локально для последующей отправки
            if scan_result.get('content'):
                backup_file = f"scan_backup_{scan_result['scan_id']}.{'pdf' if scan_result['filename'].endswith('.pdf') else 'png'}"
                try:
                    with open(backup_file, 'w') as f:
                        f.write(scan_result['content'])
                    logger.info(f"💾 Скан сохранен локально в {backup_file} для последующей отправки")
                except Exception as e:
                    logger.error(f"❌ Не удалось сохранить резервную копию: {e}")

    def signal_handler(self, sig, frame):
        """Обработчик сигналов для graceful shutdown"""
        logger.info(f"🛑 Получен сигнал {sig}, останавливаемся...")
        self.stop()

    def check_connections(self):
        """Проверяет подключения к API и сканеру"""
        logger.info("🔍 Проверка подключений...")

        # Проверка API (без test_connection)
        if not config.LARAVEL_TOKEN:
            logger.error("❌ LARAVEL_TOKEN не установлен в конфигурации")
            return False

        if not config.LARAVEL_API or config.LARAVEL_API == "http://localhost":
            logger.error("❌ LARAVEL_API не настроен правильно")
            return False

        logger.info(f"🌐 API: {config.LARAVEL_API}")
        logger.info(f"🔑 Токен: {config.LARAVEL_TOKEN[:10]}...")

        # Проверка сканера (использует кешированные данные)
        logger.info("🔍 Проверяем доступность сканера...")
        if not scanner_manager.scanner_exists():
            logger.error("❌ Указанный сканер не найден")
            return False

        scanner_device = scanner_manager.get_scanner_device()
        if not scanner_device:
            logger.error("❌ Не удалось определить устройство сканера")
            return False

        logger.info(f"✅ Сканер доступен: {scanner_device}")

        # Проверка поддержки автоподатчика
        if self.use_adf:
            if hasattr(config, 'SCANNER_ADF_OPTIONS'):
                logger.info(f"✅ Автоподатчик настроен: {config.SCANNER_ADF_OPTIONS}")
            else:
                logger.warning("⚠️ Автоподатчик включен, но SCANNER_ADF_OPTIONS не настроены")
                self.use_adf = False

        # Проверка клавиатуры
        logger.info("🎹 Проверяем клавиатуру...")
        keyboard_device = scanner_manager.find_keyboard_device()
        if not keyboard_device:
            logger.error("❌ Клавиатура не найдена")
            return False

        logger.info(f"✅ Клавиатура найдена: {keyboard_device.name}")
        logger.info(f"📍 Путь: {keyboard_device.path}")

        # Показываем доступные триггерные кнопки
        trigger_keys = getattr(config, 'SCAN_TRIGGER_KEYS', [])
        logger.info(f"🎯 Триггерные кнопки: {', '.join(trigger_keys)}")

        return True

    def start_service(self):
        """Запуск автоматической службы сканирования"""
        logger.info("🚀 Запуск автоматической службы сканирования...")

        if self.use_adf:
            logger.info("📄 Режим: С автоподатчиком документов")
        else:
            logger.info("📄 Режим: Обычное сканирование")

        # Проверяем подключения
        if not self.check_connections():
            logger.error("❌ Критические ошибки конфигурации. Завершаем работу.")
            return False

        # Регистрируем обработчики сигналов
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.is_running = True

        # Запускаем слушатель клавиатуры
        logger.info("🎹 Запускаем слушатель клавиатуры...")
        if not scanner_manager.start_keyboard_listener(self.on_scan_triggered):
            logger.error("❌ Не удалось запустить слушатель клавиатуры")
            return False

        keyboard_device = scanner_manager.find_keyboard_device()
        if keyboard_device:
            logger.info(f"✅ Слушатель клавиатуры запущен: {keyboard_device.name}")
        else:
            logger.info("✅ Слушатель клавиатуры запущен")

        logger.info("=" * 60)
        logger.info("🎯 СЛУЖБА СКАНИРОВАНИЯ АКТИВНА")
        if self.use_adf:
            logger.info("📄 РЕЖИМ: АВТОПОДАТЧИК ДОКУМЕНТОВ")
        logger.info("🎹 Нажимайте триггерные кнопки для сканирования")
        logger.info("⏹️  Нажмите Ctrl+C для остановки")
        logger.info("=" * 60)

        try:
            # Главный цикл
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n🛑 Получен сигнал остановки...")
        finally:
            self.stop()

        return True

    def stop(self):
        """Остановка службы"""
        logger.info("🛑 Останавливаем службу...")
        self.is_running = False
        scanner_manager.stop_keyboard_listener()
        logger.info("✅ Служба остановлена")

def main():
    """Основная функция"""
    print("🚀 Автоматическая служба сканирования")
    print("📝 Логи будут сохранены в auto_scan_service.log")

    service = AutoScanService()

    try:
        if service.start_service():
            print("✅ Служба завершила работу успешно")
        else:
            print("❌ Служба завершила работу с ошибками")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
