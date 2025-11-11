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
# SCANNER_DEVICE = os.getenv("DEFAULT_SCANNER", '192.168.1.163') # Замените на ID вашего сканера из scanimage -L
# SCANNER_DEVICE = os.getenv("DEFAULT_SCANNER", 'Pantum_M7100DW_Series_9AF505_USB') # Замените на ID вашего сканера из scanimage -L
SCANNER_DEVICE = os.getenv("DEFAULT_SCANNER", 'airscan:e5:Pantum M7100DW Series 9AF505 (USB)') # Замените на ID вашего сканера из scanimage -L
KEYBOARD_DEVICE =  os.getenv("DEFAULT_KEYBOARD", "/dev/input/event0")       # SIGMACH1P USB Keyboard из вашего списка

# Дополнительные устройства с кнопками (например, кнопка питания)
ADDITIONAL_INPUT_DEVICES = [
    "/dev/input/event0",  # axp20x-pek (KEY_POWER)
]

# Кнопки для запуска сканирования
SCAN_TRIGGER_KEYS = [
    'KEY_ENTER',      # Enter на основной клавиатуре
    'KEY_SPACE',      # Пробел на основной клавиатуре
    'KEY_POWER',      # Кнопка питания на axp20x-pek
    'KEY_VOLUMEUP',   # Кнопка увеличения громкости (если есть)
    'KEY_VOLUMEDOWN', # Кнопка уменьшения громкости (если есть)
    'EV_SYN',
    'EV_KEY',
    '0',
    '1',
    '116'
]

# Автоопределение устройств
AUTO_DETECT_SCANNER = False
AUTO_DETECT_KEYBOARD = False
AUTO_DETECT_BUTTONS = True  # Автоматически искать устройства с кнопками
