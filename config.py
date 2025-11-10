import os
from dotenv import load_dotenv

load_dotenv()

RABBIT_HOST = os.getenv("RABBIT_HOST", "localhost")
RABBIT_PORT = int(os.getenv("RABBIT_PORT", "5672"))
RABBIT_QUEUE = os.getenv("RABBIT_QUEUE", "print_tasks")
RABBIT_USER = os.getenv("RABBITMQ_DEFAULT_USER", "root")
RABBIT_PASS = os.getenv("RABBITMQ_DEFAULT_PASS", "password")

LARAVEL_API = os.getenv("LARAVEL_API", "http://localhost")

DEFAULT_PRINTER = os.getenv("DEFAULT_PRINTER", "OfficePrinter")
DEFAULT_METHOD = os.getenv("DEFAULT_METHOD", "raw")
PRINTER_ID = os.getenv("PRINTER_ID", "raw")
PRINTER = os.getenv("DEFAULT_PRINTER", '192.168.50.131')
DISABLE_PRINT = os.getenv("DISABLE_PRINT", "false").lower() == "true"
DISABLE_SCAN = os.getenv("DISABLE_SCAN", "false").lower() == "true"   # Если True, сканирование отключается (для отладки)

LOG_FILE = os.getenv("LOG_FILE", "/var/log/worker.log")
LARAVEL_TOKEN = os.getenv("LARAVEL_TOKEN", "")

HEARTBEAT_INTERVAL = 5


# Настройки сканера
SCANNER_FORMAT = "pdf"  # pdf или png
SCANNER_DPI = 300
SCANNER_MODE = "Color"  # Color, Gray, Lineart

# Укажите конкретные устройства
SCANNER_DEVICE = "pixma:04A91712_5A3F7F"  # Замените на ID вашего сканера из scanimage -L
KEYBOARD_DEVICE = "/dev/input/event2"      # SIGMACH1P USB Keyboard из вашего списка

# Альтернативно, можно использовать автоматическое определение
AUTO_DETECT_SCANNER = False  # Если True, будет использован первый найденный сканер
AUTO_DETECT_KEYBOARD = False # Если True, будет использована первая найденная клавиатура
