import os
import sys
import signal

# Эти переменные будут устанавливаться в worker/rabbit
connection = None
channel = None


def cleanup_file(path: str):
    """Удаление временного файла"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            print(f"Не удалось удалить {path}: {e}", file=sys.stderr)


def graceful_exit(signum, frame):
    """Корректное завершение воркера"""
    global connection, channel
    print("\n [*] Останавливаю worker...")

    try:
        if channel and channel.is_open:
            channel.close()
            print(" [*] Канал закрыт")
        if connection and connection.is_open:
            connection.close()
            print(" [*] Соединение закрыто")
    except Exception as e:
        print(" [!] Ошибка при закрытии:", e)

    sys.exit(0)
