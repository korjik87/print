#!/usr/bin/env python3
import os
import sys
import base64
import uuid
import json
from datetime import datetime
from scan_uploader import scan_uploader

def test_upload_file(file_path, custom_filename=None):
    """Тестирует отправку существующего файла"""
    if not os.path.exists(file_path):
        print(f"❌ Файл {file_path} не найден")
        return False

    # Генерируем scan_id
    scan_id = str(uuid.uuid4())
    filename = custom_filename or os.path.basename(file_path)

    try:
        # Читаем файл и кодируем в base64
        with open(file_path, 'rb') as f:
            file_content = f.read()
            content_base64 = base64.b64encode(file_content).decode('utf-8')

        # Определяем формат
        if file_path.lower().endswith('.pdf'):
            scan_format = 'pdf'
        elif file_path.lower().endswith('.png'):
            scan_format = 'png'
        elif file_path.lower().endswith(('.jpg', '.jpeg')):
            scan_format = 'jpg'
        else:
            scan_format = 'pdf'  # по умолчанию

        # Подготавливаем данные для отправки
        scan_result = {
            'scan_id': scan_id,
            'filename': filename,
            'content': content_base64,
        }

        print(f"🧪 Тестовая отправка файла: {file_path}")
        print(f"📁 Имя файла: {filename}")
        print(f"📏 Размер: {len(file_content)} байт")
        print(f"📊 Формат: {scan_format}")
        print(f"🆔 Scan ID: {scan_id}")

        upload_result = scan_uploader.upload_scan(scan_result)

        # Сохраняем метаданные
        metadata = {
            'scan_id': scan_id,
            'timestamp': datetime.now().timestamp(),
            'filename': filename,
            'file_path': file_path,
            'content_length': len(file_content),
            'scan_format': scan_format,
            'upload_status': upload_result['upload_status'],
            'upload_error': upload_result['error'],
            'response_data': upload_result.get('response_data'),
            'test_upload': True,
        }

        metadata_file = f"scan_{scan_id}.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        if upload_result['upload_status'] == 'success':
            print(f"✅ Файл успешно отправлен!")
            print(f"💾 Метаданные сохранены в {metadata_file}")
            return True
        else:
            print(f"❌ Ошибка отправки: {upload_result['error']}")
            print(f"💾 Метаданные сохранены в {metadata_file}")

            # Сохраняем копию файла для последующей отправки
            backup_file = f"scan_backup_{scan_id}.{scan_format}"
            with open(backup_file, 'wb') as f:
                f.write(file_content)
            print(f"💾 Резервная копия сохранена в {backup_file}")

            return False

    except Exception as e:
        print(f"❌ Ошибка при обработке файла: {e}")
        return False

def test_upload_directory(directory_path):
    """Тестирует отправку всех файлов в директории"""
    if not os.path.exists(directory_path):
        print(f"❌ Директория {directory_path} не найдена")
        return

    supported_extensions = ['.pdf', '.png', '.jpg', '.jpeg']
    files_to_upload = []

    for file in os.listdir(directory_path):
        file_path = os.path.join(directory_path, file)
        if os.path.isfile(file_path):
            ext = os.path.splitext(file)[1].lower()
            if ext in supported_extensions:
                files_to_upload.append(file_path)

    if not files_to_upload:
        print(f"❌ В директории {directory_path} нет поддерживаемых файлов")
        return

    print(f"📁 Найдено файлов для отправки: {len(files_to_upload)}")

    success_count = 0
    for file_path in files_to_upload:
        print("\n" + "="*50)
        if test_upload_file(file_path):
            success_count += 1
        print("="*50)

    print(f"\n📊 Итоги тестирования:")
    print(f"  ✅ Успешно: {success_count}")
    print(f"  ❌ Неудачно: {len(files_to_upload) - success_count}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python3 test_upload.py <путь_к_файлу> [новое_имя_файла]")
        print("  python3 test_upload.py --dir <путь_к_директории>")
        sys.exit(1)

    if sys.argv[1] == "--dir":
        if len(sys.argv) > 2:
            test_upload_directory(sys.argv[2])
        else:
            print("❌ Укажите путь к директории")
    else:
        file_path = sys.argv[1]
        custom_name = sys.argv[2] if len(sys.argv) > 2 else None
        test_upload_file(file_path, custom_name)
