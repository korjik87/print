#!/bin/bash

# Скрипт автоматической настройки после git pull
# Для системы сканирования/печати

set -e  # Выход при ошибке

echo "🔄 Настройка системы после git pull..."
echo "========================================"

# Проверяем, запущен ли скрипт из правильной директории
if [ ! -f "auto_scan_service.py" ]; then
    echo "❌ Ошибка: Запустите скрипт из корневой директории проекта"
    exit 1
fi

# Функция для проверки прав
check_permissions() {
    echo "🔐 Проверка прав доступа..."
    if [ "$EUID" -ne 0 ]; then
        echo "⚠️  Рекомендуется запустить скрипт с sudo для установки системных сервисов"
    fi
}

# Функция установки зависимостей Python
install_python_deps() {
    echo "📦 Установка Python зависимостей..."

    # Обновляем pip
    pip3 install --upgrade pip

    # Устанавливаем зависимости
    echo "📚 Устанавливаем зависимости из requirements.txt..."
    if [ -f "requirements.txt" ]; then
        pip3 install -r requirements.txt
    else
        # Базовые зависимости
        pip3 install evdev python-daemon
        echo "✅ Базовые зависимости установлены"
    fi

    # Проверяем установку evdev
    if python3 -c "import evdev" 2>/dev/null; then
        echo "✅ evdev установлен"
    else
        echo "❌ Ошибка: не удалось установить evdev"
        exit 1
    fi
}

# Функция настройки системных сервисов
setup_systemd_services() {
    if [ "$EUID" -ne 0 ]; then
        echo "⏩ Пропускаем настройку systemd (требуются права root)"
        return 0
    fi

    echo "⚙️  Настройка systemd сервисов..."

    # Получаем абсолютный путь к проекту
    PROJECT_DIR=$(pwd)
    PROJECT_NAME=$(basename "$PROJECT_DIR")
    PARENT_DIR=$(dirname "$PROJECT_DIR")

    echo "📁 Директория проекта: $PROJECT_DIR"
    echo "📁 Родительская директория: $PARENT_DIR"
    echo "📁 Имя проекта: $PROJECT_NAME"

    # Создаем сервис для автоматического сканирования
    cat > /etc/systemd/system/auto-scan.service << EOF
[Unit]
Description=Auto Scan Service
After=network.target multi-user.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 $PROJECT_DIR/auto_scan_service.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONPATH=$PROJECT_DIR

[Install]
WantedBy=multi-user.target
EOF

    # Создаем сервис для печати (если есть)
    if [ -f "worker.py" ]; then
        cat > /etc/systemd/system/print-service.service << EOF
[Unit]
Description=Print Service
After=network.target
Requires=auto-scan.service

[Service]
Type=simple
User=root
WorkingDirectory=$PARENT_DIR
ExecStart=/usr/bin/python3 -m $PROJECT_NAME.worker
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONPATH=$PROJECT_DIR

[Install]
WantedBy=multi-user.target
EOF
    fi

    # Создаем сервис для отправки печати (если есть)
    if [ -f "upload_service.py" ]; then
        cat > /etc/systemd/system/print-send-service.service << EOF
[Unit]
Description=Print Send Service
After=network.target print-service.service
Requires=print-service.service

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 $PROJECT_DIR/upload_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONPATH=$PROJECT_DIR

[Install]
WantedBy=multi-user.target
EOF
    fi

    # Перезагружаем демон systemd
    systemctl daemon-reload
    echo "✅ Systemd сервисы созданы"
}

# Функция настройки прав на устройства
setup_device_permissions() {
    echo "🎮 Настройка прав доступа к устройствам..."

    # Создаем правило udev для сканера (если нужно)
    if [ "$EUID" -eq 0 ]; then
        cat > /etc/udev/rules.d/99-scanner-permissions.rules << EOF
# Права для устройств сканирования
SUBSYSTEM=="usb", ATTRS{idVendor}=="04a9", MODE="0666"  # Пример для Canon
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", MODE="0666"  # Пример для Epson
KERNEL=="event*", MODE="0666"  # Права на события клавиатуры
EOF

        # Применяем правила udev
        udevadm control --reload-rules
        udevadm trigger
        echo "✅ Правила udev применены"
    else
        echo "ℹ️  Для настройки прав udev запустите скрипт с sudo"
    fi
}

# Функция создания необходимых директорий
create_directories() {
    echo "📁 Создание рабочих директорий..."

    directories=(
        "scans_storage"
        "logs"
        "temp"
        "config"
    )

    for dir in "${directories[@]}"; do
        if [ ! -d "$dir" ]; then
            mkdir -p "$dir"
            echo "✅ Создана директория: $dir"
        fi
    done

    # Устанавливаем права на запись
    chmod 755 scans_storage logs temp
}

# Функция проверки конфигурации
check_configuration() {
    echo "🔧 Проверка конфигурации..."

    # Проверяем наличие config.py
    if [ ! -f "config.py" ]; then
        echo "⚠️  Файл config.py не найден. Создайте его на основе config.example.py"
        if [ -f "config.example.py" ]; then
            cp config.example.py config.py
            echo "✅ Создан config.py из примера"
        fi
    fi

    # Проверяем базовые настройки
    if python3 -c "import config; print('✅ Конфигурация загружается')" 2>/dev/null; then
        echo "✅ Конфигурация в порядке"
    else
        echo "❌ Ошибка в конфигурации"
    fi
}

# Функция запуска сервисов
start_services() {
    if [ "$EUID" -ne 0 ]; then
        echo "⏩ Запуск сервисов пропущен (требуются права root)"
        return 0
    fi

    echo "🚀 Запуск сервисов..."

    # Включаем автозапуск
    systemctl enable auto-scan.service
    echo "✅ Автозапуск auto-scan.service включен"

    if [ -f "worker.py" ]; then
        systemctl enable print-service.service
        echo "✅ Автозапуск print-service.service включен"
    fi

    if [ -f "upload_service.py" ]; then
        systemctl enable print-send-service.service
        echo "✅ Автозапуск print-send-service.service включен"
    fi

    # Перезапускаем сервисы
    systemctl restart auto-scan.service
    echo "✅ Сервис auto-scan.service перезапущен"

    if [ -f "worker.py" ]; then
        systemctl restart print-service.service
        echo "✅ Сервис print-service.service перезапущен"
    fi

    if [ -f "upload_service.py" ]; then
        systemctl restart print-send-service.service
        echo "✅ Сервис print-send-service.service перезапущен"
    fi
}

# Функция отображения статуса
show_status() {
    echo ""
    echo "========================================"
    echo "✅ НАСТРОЙКА ЗАВЕРШЕНА"
    echo "========================================"

    if [ "$EUID" -eq 0 ]; then
        echo "📊 Статус сервисов:"
        systemctl status auto-scan.service --no-pager -l

        if [ -f "worker.py" ]; then
            systemctl status print-service.service --no-pager -l
        fi

        if [ -f "upload_service.py" ]; then
            systemctl status print-send-service.service --no-pager -l
        fi

        echo ""
        echo "🔧 Команды управления:"
        echo "   sudo systemctl status auto-scan.service"
        echo "   sudo journalctl -u auto-scan.service -f"
        echo "   sudo systemctl restart auto-scan.service"
        echo "   sudo systemctl status print-service.service"
        echo "   sudo journalctl -u print-service.service -f"
    else
        echo "🔧 Для управления сервисами запустите:"
        echo "   sudo systemctl status auto-scan.service"
        echo "   sudo systemctl status print-service.service"
    fi

    echo ""
    echo "📁 Директории проекта:"
    echo "   Scans: $(pwd)/scans_storage/"
    echo "   Logs:  $(pwd)/logs/"
    echo "   Config: $(pwd)/config.py"
}

# Главная функция
main() {
    echo "🔧 Настройка системы сканирования/печати"
    echo "========================================"

    check_permissions
    install_python_deps
    create_directories
    check_configuration
    setup_device_permissions
    setup_systemd_services
    start_services
    show_status

    echo ""
    echo "🎉 Настройка завершена успешно!"
}

# Запуск главной функции
main
