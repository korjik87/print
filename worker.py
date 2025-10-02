import signal
import sys
from . import config
from .utils import graceful_exit, setup_logger, get_printer_status
from .callback import send_callback
from .rabbit import start_rabbit
from .heartbeat import start_heartbeat_thread
from .printer import print_file

# создаём логгер сразу, до всего остального
logger = setup_logger()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    status = get_printer_status(config.PRINTER)
    logger.info(f"Статус принтера {config.PRINTER}: {status}")
    print(f"Статус принтера {config.PRINTER}: {status}")

    logger.info(f"[*] Worker {config.PRINTER_ID} запущен. Очередь: print_tasks_printer_{config.PRINTER_ID}")
    print(f" [*] Worker {config.PRINTER_ID} запущен. Очередь: print_tasks_printer_{config.PRINTER_ID}")

    if config.DISABLE_PRINT:
        logger.warning("Внимание: печать ОТКЛЮЧЕНА (тестовый режим)")
        print(" [!] Внимание: печать ОТКЛЮЧЕНА (тестовый режим)")

    # heartbeat запускаем после логгера
    start_heartbeat_thread(logger)

    start_rabbit()
