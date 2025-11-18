#!/usr/bin/env python3
import os
import sys
import config

# Добавляем текущую директорию в путь Python
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from evdev import ecodes, InputDevice
except ImportError:
    print("❌ Модуль evdev не установлен. Установите: pip install evdev")
    sys.exit(1)

from scanner import scanner_manager

def test_keyboard():
    """Тестирует клавиатуру отдельно от основного приложения"""
    print("🎹 Тестирование клавиатуры...")

    keyboard_device = scanner_manager.find_keyboard_device()
    if keyboard_device:
        print(f"✅ Клавиатура найдена: {keyboard_device.name}")
        print(f"📍 Путь: {keyboard_device.path}")

        # Показываем доступные кнопки
        caps = keyboard_device.capabilities()
        if ecodes.EV_KEY in caps:
            keys = caps[ecodes.EV_KEY]
            print(f"🎯 Поддерживаемые кнопки: {len(keys)}")

        print("\n🎯 Тестируем события клавиатуры...")
        print("   Нажмите любую клавишу на клавиатуре (для выхода нажмите ESC)")
        print("   Или нажмите Ctrl+C для выхода")

        try:
            for event in keyboard_device.read_loop():
                # ФИЛЬТРУЕМ ТОЛЬКО СОБЫТИЯ КЛАВИШ И ТОЛЬКО НАЖАТИЯ
                if event.type == ecodes.EV_KEY and event.value == 1:
                    # Пытаемся получить имя клавиши
                    try:
                        key_name = ecodes.KEY[event.code]
                    except KeyError:
                        key_name = f'UNKNOWN_{event.code}'

                    print(f"   🔘 Нажата кнопка: {key_name} (код: {event.code})")

                    # Выход по ESC
                    if key_name == 'KEY_ESC':
                        print("   🛑 Выход из теста клавиатуры")
                        break

        except KeyboardInterrupt:
            print("\n   🛑 Прервано пользователем")

    else:
        print("❌ Клавиатура не найдена")

if __name__ == "__main__":
    test_keyboard()
