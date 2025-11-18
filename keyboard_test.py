#!/usr/bin/env python3
import os
import sys

# Добавляем текущую директорию в путь Python
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from evdev import ecodes, InputDevice, categorize
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

            # Показываем только кнопки из SCAN_TRIGGER_KEYS
            trigger_keys = getattr(config, 'SCAN_TRIGGER_KEYS', [])
            available_trigger_keys = []

            for key_name in trigger_keys:
                key_code = getattr(ecodes, key_name, None)
                if key_code and key_code in keys:
                    available_trigger_keys.append(key_name)

            print(f"🎯 Доступные триггерные кнопки: {', '.join(available_trigger_keys)}")

        print("\n🎯 Тестируем события клавиатуры...")
        print("   Нажмите любую клавишу на клавиатуре (для выхода нажмите ESC)")
        print("   Или нажмите Ctrl+C для выхода")

        try:
            for event in keyboard_device.read_loop():
                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    if key_event.keystate == key_event.key_down:
                        print(f"   🔘 Нажата кнопка: {key_event.keycode} (код: {event.code}, значение: {event.value})")

                        # Выход по ESC
                        if key_event.keycode == 'KEY_ESC':
                            print("   🛑 Выход из теста клавиатуры")
                            break
        except KeyboardInterrupt:
            print("\n   🛑 Прервано пользователем")

    else:
        print("❌ Клавиатура не найдена")

if __name__ == "__main__":
    test_keyboard()
