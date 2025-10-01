import signal
import sys
from . import config
from .utils import graceful_exit
from .printer import print_file
from .utils import setup_logger
from .utils import get_printer_status
from .callback import send_callback
from .rabbit import start_rabbit
from .heartbeat import start_heartbeat_thread

start_heartbeat_thread()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    status = get_printer_status(config.PRINTER)
    print(f"Статус принтера {config.PRINTER}: {status}")
    print(f" [*] Worker {config.PRINTER_ID} запущен. Очередь: print_tasks_printer_{config.PRINTER_ID}")
    if config.DISABLE_PRINT:
        print(" [!] Внимание: печать ОТКЛЮЧЕНА (тестовый режим)")

    start_rabbit()
    logger = setup_logger()



    logger.info(f"Статус принтера {config.PRINTER}: {status}")

