#!/usr/bin/env python3
from evdev import UInput, ecodes
import time
import sys

def trigger_key(key_name='KEY_ENTER'):
    """Простой скрипт для эмуляции нажатия клавиши"""
    try:
        key_code = getattr(ecodes, key_name)

        print(f"🎯 Эмулируем нажатие: {key_name}")

        with UInput() as ui:
            # Нажатие
            ui.write(ecodes.EV_KEY, key_code, 1)
            ui.syn()
            time.sleep(0.05)

            # Отпускание
            ui.write(ecodes.EV_KEY, key_code, 0)
            ui.syn()

        print(f"✅ {key_name} отправлен!")

    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        trigger_key(sys.argv[1])
    else:
        # Тестируем основные кнопки
        for key in ['KEY_ENTER', 'KEY_SPACE', 'KEY_1']:
            trigger_key(key)
            time.sleep(1)
