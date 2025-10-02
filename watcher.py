import os
import time
import subprocess
import signal
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WORKER_CMD = ["python3", "-m", "print.worker"]
WATCH_DIR = os.path.dirname(os.path.abspath(__file__))  # следим за текущей папкой
process = None

def start_worker():
    global process
    print("[watcher] Запускаю worker...")
    process = subprocess.Popen(WORKER_CMD, preexec_fn=os.setsid)

def stop_worker():
    global process
    if process and process.poll() is None:
        print("[watcher] Останавливаю worker...")
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait()
    process = None

def restart_worker():
    print("[watcher] Перезапуск worker...")
    stop_worker()
    time.sleep(1)
    start_worker()

class ChangeHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".py"):
            print(f"[watcher] Изменён файл: {event.src_path}")
            restart_worker()

def watch():
    event_handler = ChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=True)
    observer.start()

    start_worker()

    try:
        while True:
            time.sleep(1)
            if process and process.poll() is not None:
                print("[watcher] Worker упал. Перезапускаю...")
                restart_worker()
    except KeyboardInterrupt:
        observer.stop()
        stop_worker()
    observer.join()

if __name__ == "__main__":
    watch()
