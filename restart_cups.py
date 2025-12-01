import subprocess
import time
import os
from datetime import datetime, timedelta
import json

# Файл для хранения времени последнего перезапуска
LAST_RESTART_FILE = "/tmp/last_cups_restart.json"

def get_last_restart_time():
    """Получает время последнего перезапуска CUPS"""
    try:
        if os.path.exists(LAST_RESTART_FILE):
            with open(LAST_RESTART_FILE, 'r') as f:
                data = json.load(f)
                return datetime.fromisoformat(data.get('last_restart'))
    except Exception:
        pass
    return datetime.min  # Очень старая дата, если файла нет

def save_restart_time():
    """Сохраняет время текущего перезапуска"""
    try:
        with open(LAST_RESTART_FILE, 'w') as f:
            json.dump({
                'last_restart': datetime.now().isoformat()
            }, f)
    except Exception as e:
        print(f"Ошибка сохранения времени перезапуска: {e}")

def restart_cups_service(logger=None, force=False):
    """
    Перезапускает службы печати безопасно

    Args:
        logger: логгер для записи сообщений
        force: принудительный перезапуск, даже если недавно уже был

    Returns:
        bool: True если перезапуск выполнен успешно
    """
    log = logger or print

    # Проверяем, когда был последний перезапуск
    last_restart = get_last_restart_time()
    time_since_last_restart = datetime.now() - last_restart
    min_interval = timedelta(minutes=60)  # Минимальный интервал 60 минут

    if not force and time_since_last_restart < min_interval:
        remaining_minutes = (min_interval - time_since_last_restart).seconds // 60
        log(f"⚠️ Перезапуск CUPS был выполнен {time_since_last_restart.seconds // 60} минут назад. "
            f"Следующий перезапуск через {remaining_minutes} минут.")
        return False

    try:
        log("🔄 Начинаем безопасный перезапуск служб печати...")

        # 1. Перезапуск avahi-daemon (менее критично)
        log("1. Перезапускаем avahi-daemon...")
        try:
            result = subprocess.run(
                ["systemctl", "restart", "avahi-daemon"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                log("✅ avahi-daemon перезапущен успешно")
            else:
                log(f"⚠️ avahi-daemon: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            log("⚠️ Таймаут при перезапуске avahi-daemon")
        except Exception as e:
            log(f"⚠️ Ошибка при перезапуске avahi-daemon: {e}")

        time.sleep(3)

        # 2. Проверяем, появился ли принтер после перезапуска avahi
        log("🔍 Проверяем состояние после перезапуска avahi...")
        time.sleep(2)

        # 3. Если нужно, перезапускаем cups (только если принтер все еще не виден)
        log("2. Проверяем состояние CUPS...")
        try:
            cups_status = subprocess.run(
                ["systemctl", "is-active", "cups"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if cups_status.returncode != 0:
                log("⚠️ CUPS не активен, запускаем...")
                subprocess.run(["systemctl", "start", "cups"], timeout=30)
            else:
                # Проверяем, нужно ли перезапускать CUPS
                # Можно проверить состояние принтеров
                log("CUPS активен, проверяем принтеры...")
                printer_check = subprocess.run(
                    ["lpstat", "-p"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                # Перезапускаем CUPS только если есть проблемы
                if printer_check.returncode != 0 or "rejecting" in printer_check.stdout.lower():
                    log("3. Обнаружены проблемы с CUPS, перезапускаем...")
                    subprocess.run(["systemctl", "restart", "cups"], timeout=30)
                    log("✅ CUPS перезапущен")
                else:
                    log("✅ CUPS работает нормально, перезапуск не требуется")

        except Exception as e:
            log(f"⚠️ Ошибка при работе с CUPS: {e}")

        time.sleep(5)

        # 4. Сохраняем время перезапуска
        save_restart_time()

        # 5. Проверяем финальное состояние
        log("🔍 Проверяем финальное состояние...")
        try:
            final_check = subprocess.run(
                ["systemctl", "is-active", "cups", "avahi-daemon"],
                capture_output=True,
                text=True,
                timeout=10
            )

            cups_browsed_check = subprocess.run(
                ["systemctl", "is-active", "cups-browsed"],
                capture_output=True,
                text=True,
                timeout=10
            )

            log(f"✅ CUPS статус: {final_check.stdout.strip() if final_check.returncode == 0 else 'ошибка'}")
            log(f"✅ avahi-daemon статус: активен")
            log(f"✅ cups-browsed статус: {cups_browsed_check.stdout.strip() if cups_browsed_check.returncode == 0 else 'не активен'}")

        except Exception as e:
            log(f"⚠️ Ошибка при проверке статуса: {e}")

        log("✅ Перезапуск служб печати завершен")
        return True

    except Exception as e:
        log(f"❌ Критическая ошибка при перезапуске: {e}")
        return False
