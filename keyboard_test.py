#!/usr/bin/env python3
import os
import sys

# Добавляем текущую директорию в путь Python
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from evdev import InputDevice, ecodes, list_devices
except ImportError:
    print("❌ Модуль evdev не установлен. Установите: pip install evdev")
    sys.exit(1)

def test_keyboard():
    """Тестирует клавиатуру - срабатывает на ЛЮБОЕ нажатие"""
    print("🎹 Тестирование клавиатуры...")
    
    # Находим устройство ввода
    devices = [InputDevice(path) for path in list_devices()]
    if not devices:
        print("❌ Устройства ввода не найдены")
        return
    
    # Используем первое найденное устройство
    device = devices[0]
    print(f"✅ Используем устройство: {device.name}")
    print(f"📍 Путь: {device.path}")
    
    print("\n🎯 Тестируем события клавиатуры...")
    print("   Нажмите любую клавишу (для выхода нажмите ESC)")
    print("   Или нажмите Ctrl+C для выхода")
    
    try:
        for event in device.read_loop():
            # Обрабатываем только события клавиш
            if event.type == ecodes.EV_KEY:
                # Получаем имя клавиши
                try:
                    key_name = ecodes.KEY[event.code]
                except KeyError:
                    key_name = f'UNKNOWN_{event.code}'
                
                # Показываем только нажатия (не отпускания)
                if event.value == 1:  # 1 = нажатие, 0 = отпускание, 2 = удерживается
                    print(f"   🔘 Нажата кнопка: {key_name}")
                    
                    # Выход по ESC
                    if key_name == 'KEY_ESC':
                        print("   🛑 Выход из теста клавиатуры")
                        break
                        
    except KeyboardInterrupt:
        print("\n   🛑 Прервано пользователем")

if __name__ == "__main__":
    test_keyboard()
