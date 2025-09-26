import os
from dotenv import load_dotenv

load_dotenv()

RABBIT_HOST = os.getenv("RABBIT_HOST", "localhost")
RABBIT_PORT = int(os.getenv("RABBIT_PORT", "5672"))
RABBIT_QUEUE = os.getenv("RABBIT_QUEUE", "print_tasks")

LARAVEL_API = os.getenv("LARAVEL_API", "http://localhost")

DEFAULT_PRINTER = os.getenv("DEFAULT_PRINTER", "OfficePrinter")
DEFAULT_METHOD = os.getenv("DEFAULT_METHOD", "raw")
PRINTER_ID = os.getenv("PRINTER_ID", "raw")
PRINTER = os.getenv("DEFAULT_PRINTER", '192.168.50.131')
DISABLE_PRINT = os.getenv("DISABLE_PRINT", "false").lower() == "true"
