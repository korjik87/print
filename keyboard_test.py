#!/usr/bin/env python3
import os
import sys
import config

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

        print("\n🎯 Тестируем ВСЕ события клавиатуры...")
        print("   Нажмите любую клавишу на клавиатуре (для выхода нажмите ESC)")
        print("   Или нажмите Ctrl+C для выхода")
        print("   Будут отображаться ВСЕ события устройства")

        try:
            for event in keyboard_device.read_loop():
                # Определяем тип события
                event_type = "UNKNOWN"
                if event.type == ecodes.EV_KEY:
                    event_type = "EV_KEY"
                elif event.type == ecodes.EV_SYN:
                    event_type = "EV_SYN"
                elif event.type == ecodes.EV_REL:
                    event_type = "EV_REL"
                elif event.type == ecodes.EV_ABS:
                    event_type = "EV_ABS"
                elif event.type == ecodes.EV_MSC:
                    event_type = "EV_MSC"

                # Для событий клавиш показываем дополнительную информацию
                if event.type == ecodes.EV_KEY:
                    try:
                        key_name = ecodes.KEY[event.code]
                    except KeyError:
                        key_name = f'UNKNOWN_{event.code}'

                    if event.value == 0:
                        state = "отпущена"
                    elif event.value == 1:
                        state = "нажата"
                    elif event.value == 2:
                        state = "удерживается"
                    else:
                        state = f"неизвестно ({event.value})"

                    print(f"   🔘 Событие: {event_type}, Клавиша: {key_name} (код: {event.code}), состояние: {state}")

                    # Выход по ESC (только при нажатии)
                    if key_name == 'KEY_ESC' and event.value == 1:
                        print("   🛑 Выход из теста клавиатуры")
                        break
                else:
                    # Для не-клавишных событий показываем базовую информацию
                    print(f"   📝 Событие: {event_type}, код: {event.code}, значение: {event.value}")

        except KeyboardInterrupt:
            print("\n   🛑 Прервано пользователем")

    else:
        print("❌ Клавиатура не найдена")

if __name__ == "__main__":
    test_keyboard()
