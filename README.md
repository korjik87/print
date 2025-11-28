# 📘 Инструкция по установке **Scan-Print System**

## 1. Подготовка системы

### 1.1. Установка системных зависимостей
```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y     python3     python3-pip     python3-venv     git     sane     sane-utils     imagemagick     poppler-utils     systemd
```



## 2. Установка проекта

### 2.1. Клонирование репозитория
```bash
cd /opt
sudo git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> scan-print-system
sudo chown -R $USER:$USER scan-print-system
cd scan-print-system
```

### 2.2. Установка Python-зависимостей
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Конфигурация системы

### 3.1. Получение данных с сервера Laravel API

Перед настройкой получите:

- Токен авторизации (LARAVEL_TOKEN)
- Данные RabbitMQ (хост, порт, пользователь, пароль)
- ID принтера

### 3.2. Создание файла `.env`
```env
LARAVEL_API=http://217.16.23.201
LARAVEL_TOKEN=ваш_токен_с_сервера
RABBIT_HOST=хост_rabbitmq_с_сервера
RABBIT_PORT=5672
RABBIT_QUEUE=print_tasks
RABBITMQ_DEFAULT_USER=пользователь_с_сервера
RABBITMQ_DEFAULT_PASS=пароль_с_сервера
PRINTER_ID=уникальный_id
DEFAULT_PRINTER=192.168.50.131
DEFAULT_SCANNER=airscan:e5:Pantum M7100DW Series 9AF505 (USB)
DEFAULT_KEYBOARD=/dev/input/event0
DISABLE_PRINT=false
DISABLE_SCAN=false
LOG_FILE=/var/log/worker.log
```

### 3.3. Определение устройств

```bash
scanimage -L
python3 -c "from evdev import list_devices; print([(d, InputDevice(d).name) for d in list_devices()])"
```

---

## 4. Настройка сервисов

### 4.1. Автоматическая настройка
```bash
chmod +x setup_after_pull.sh
sudo ./setup_after_pull.sh
```

### 4.2. Ручная настройка
```bash
sudo systemctl daemon-reload
sudo systemctl enable auto-scan.service
sudo systemctl enable print-service.service
sudo cp 99-scanner-permissions.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

---

## 5. Проверка работы

### 5.1. Проверка сканера
```bash
scanimage -L
scanimage > test.pnm
```


### 5.3. Проверка RabbitMQ
```bash
python3 -c "
import pika
from config import RABBIT_HOST, RABBIT_PORT, RABBIT_USER, RABBIT_PASS
credentials = pika.PlainCredentials(RABBIT_USER, RABBIT_PASS)
connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBIT_HOST, port=RABBIT_PORT, credentials=credentials))
print('УСПЕШНО')
connection.close()
"
```

### 5.4. Запуск сервисов
```bash
sudo systemctl start auto-scan.service
sudo systemctl start print-service.service
sudo systemctl status auto-scan.service
sudo systemctl status print-service.service
```

---

## 6. Тестирование
- Проверка сканирования
- Проверка печати
- Проверка логов

---

## 7. Мониторинг и логи

```bash
sudo journalctl -u auto-scan.service -f
sudo journalctl -u print-service.service -f
tail -f /var/log/worker.log
```

---

## 8. Обновление
```bash
cd /opt/scan-print-system
git pull
sudo ./setup_after_pull.sh
```
