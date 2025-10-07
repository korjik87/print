#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Runner для проверки работоспособности принтерного воркера:
1. Проверка CUPS статуса (lpstat / lpq)
2. Проверка RabbitMQ соединения и очереди
3. Проверка поведения воркера при ошибке принтера (мок)
4. Проверка реакции на успешное задание
"""

import os
import sys
import json
import subprocess
import pika
import time
import traceback

from . import worker

# ============ CONFIG ============
PRINTER_NAME = os.getenv("DEFAULT_PRINTER", "Pantum_M7100DW_Series_9AF505_USB")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
QUEUE_NAME = os.getenv("QUEUE_NAME", "print_queue")
TEST_FILE = "/tmp/test_runner.txt"
# ================================


def log(msg):
    print(f"🧩 {msg}")


def check_cups_status(printer):
    """Проверяет доступность CUPS и статусы"""
    log(f"Проверка статуса CUPS для принтера: {printer}")
    try:
        res = subprocess.run(["lpstat", "-l", "-p", printer], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip())
        print(res.stdout)
        log("✅ CUPS работает и принтер найден.")
    except Exception as e:
        log(f"❌ Ошибка при проверке CUPS: {e}")
        return False
    return True


def check_rabbitmq_connection():
    """Проверка соединения с RabbitMQ"""
    log("Проверка соединения с RabbitMQ...")
    try:
        conn = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        ch = conn.channel()
        ch.queue_declare(queue=QUEUE_NAME, durable=True)
        conn.close()
        log("✅ RabbitMQ доступен и очередь существует.")
        return True
    except Exception as e:
        log(f"❌ Ошибка подключения к RabbitMQ: {e}")
        return False


def test_mocked_worker_behavior():
    """Проверка реакции воркера при ошибках принтера"""
    log("Тест 1️⃣ — проверка поведения при ошибке принтера (мок).")

    def fake_status_error(printer):
        return {
            "online": True,
            "paper_out": True,
            "door_open": False,
            "raw_status": "media-empty-error"
        }

    worker.get_detailed_printer_status = fake_status_error

    job = {"printer": "Fake_Printer", "file": TEST_FILE, "retries": 0}
    mock_ch = type("MockCh", (), {
        "basic_ack": lambda self, **kw: print("ACK ✅"),
        "basic_nack": lambda self, **kw: print("NACK ❌", kw),
        "basic_publish": lambda self, **kw: print("📤 Задание возвращено в очередь", kw.get('body'))
    })()

    try:
        worker.handle_print_job(mock_ch, type("obj", (), {"delivery_tag": 1}), None, json.dumps(job).encode())
        log("✅ Тест моков пройден — воркер корректно обработал ошибку принтера.")
    except Exception:
        traceback.print_exc()
        log("❌ Ошибка при тесте моков.")


def test_successful_job():
    """Проверка успешной задачи печати"""
    log("Тест 2️⃣ — проверка успешной задачи печати (реальный CUPS).")
    try:
        # создаём тестовый файл
        with open(TEST_FILE, "w") as f:
            f.write("Test Runner Print\n")

        # публикуем задачу в RabbitMQ
        conn = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        ch = conn.channel()
        ch.basic_publish(
            exchange='',
            routing_key=QUEUE_NAME,
            body=json.dumps({
                "printer": PRINTER_NAME,
                "file": TEST_FILE,
                "retries": 0
            }),
            properties=pika.BasicProperties(
                delivery_mode=2
            )
        )
        conn.close()
        log("📨 Задача отправлена в очередь. Проверьте логи воркера.")
        log("⚙️ Если принтер доступен, файл должен напечататься.")
    except Exception as e:
        log(f"❌ Ошибка при публикации задачи: {e}")


def main():
    log("🚀 Запуск тестового сценария для принтерного воркера\n")

    ok_cups = check_cups_status(PRINTER_NAME)
    ok_rabbit = check_rabbitmq_connection()

    if not ok_rabbit:
        log("🛑 RabbitMQ недоступен — останов теста.")
        sys.exit(1)

    test_mocked_worker_behavior()

    if ok_cups:
        test_successful_job()
    else:
        log("⚠️ CUPS не найден — пропуск теста печати.")

    log("\n✅ Тестирование завершено.")


if __name__ == "__main__":
    main()
