#!/usr/bin/env python3
import os
import json
import glob
import sys
import logging
from datetime import datetime

# Импортируем конфигурацию
import config
from upload_service import UploadService

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def get_storage_dir():
    """Возвращает путь к директории хранения сканов"""
    return "scans_storage"

def find_scan_files(scan_id):
    """Находит файлы скана по ID в директории scans_storage"""
    storage_dir = get_storage_dir()

    # Ищем JSON файл в scans_storage
    json_file = os.path.join(storage_dir, f"scan_{scan_id}.json")
    if not os.path.exists(json_file):
        print(f"❌ Файл метаданных {json_file} не найден")
        return None, None

    try:
        with open(json_file, 'r') as f:
            metadata = json.load(f)

        # Пытаемся получить путь из метаданных
        scan_file = metadata.get('file_path')
        if scan_file and os.path.exists(scan_file):
            return json_file, scan_file

        # Если в метаданных нет пути, ищем по шаблону в scans_storage
        pdf_file = os.path.join(storage_dir, f"scan_{scan_id}.pdf")
        png_file = os.path.join(storage_dir, f"scan_{scan_id}.png")

        if os.path.exists(pdf_file):
            return json_file, pdf_file
        elif os.path.exists(png_file):
            return json_file, png_file
        else:
            print(f"❌ Файл скана для {scan_id} не найден в {storage_dir}")
            return json_file, None

    except Exception as e:
        print(f"❌ Ошибка чтения метаданных: {e}")
        return json_file, None

def retry_specific_scan(scan_id):
    """Повторно отправляет конкретный скан по ID"""
    print(f"🔄 Повторная отправка скана {scan_id}...")

    # Ищем файлы в scans_storage
    json_file, scan_file = find_scan_files(scan_id)

    if not json_file or not scan_file:
        return False

    try:
        # Читаем метаданные
        with open(json_file, 'r') as f:
            metadata = json.load(f)

        # Создаем экземпляр UploadService для отправки
        upload_service = UploadService()

        # Подготавливаем данные для отправки
        upload_data = {
            'scan_id': scan_id,
            'filename': metadata.get('original_filename', os.path.basename(scan_file)),
            'file_path': scan_file,
            'dpi': metadata.get('dpi', config.SCANNER_DPI),
            'mode': metadata.get('mode', config.SCANNER_MODE),
            'scanner_device': metadata.get('scanner_device', 'python_retry'),
            'additional_metadata': {
                'original_path': scan_file,
                'file_size': os.path.getsize(scan_file),
                'retry_attempt': metadata.get('upload_attempts', 0) + 1,
                'retry_timestamp': datetime.now().isoformat()
            }
        }

        # Отправляем скан
        upload_result = upload_service.upload_scan(upload_data)

        if upload_result['upload_status'] == 'success':
            print(f"✅ Скан {scan_id} успешно отправлен в очередь!")

            # Обновляем метаданные в соответствии с новой логикой
            metadata.update({
                'status': 'queued',
                'uploaded_to_server_at': datetime.now().isoformat(),
                'upload_attempts': metadata.get('upload_attempts', 0) + 1,
                'last_upload_attempt': datetime.now().isoformat(),
                'server_response': upload_result.get('response_data'),
                'scan_record_id': upload_result.get('scan_record_id'),
                'upload_error': None,
                'queue_status': 'waiting'
            })

            with open(json_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            return True
        else:
            print(f"❌ Ошибка отправки: {upload_result['error']}")

            # Обновляем метаданные с ошибкой
            metadata.update({
                'status': 'error',
                'upload_attempts': metadata.get('upload_attempts', 0) + 1,
                'last_upload_attempt': datetime.now().isoformat(),
                'upload_error': upload_result['error'],
                'queue_status': 'error'
            })

            with open(json_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            return False

    except Exception as e:
        print(f"❌ Ошибка при обработке скана {scan_id}: {e}")

        # Обновляем метаданные с информацией об ошибке
        try:
            with open(json_file, 'r') as f:
                metadata = json.load(f)

            metadata.update({
                'status': 'error',
                'upload_attempts': metadata.get('upload_attempts', 0) + 1,
                'last_upload_attempt': datetime.now().isoformat(),
                'upload_error': str(e),
                'queue_status': 'error'
            })

            with open(json_file, 'w') as f:
                json.dump(metadata, f, indent=2)
        except:
            pass

        return False

def retry_all_failed():
    """Повторно отправляет все сканы с ошибками"""
    print("🔄 Повторная отправка всех сканов с ошибками...")

    storage_dir = get_storage_dir()
    json_files = glob.glob(os.path.join(storage_dir, "scan_*.json"))
    failed_scans = []

    # Находим сканы с ошибками
    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                metadata = json.load(f)

            # Ищем сканы с ошибками или pending статусом
            status = metadata.get('status')
            if status in ['error', 'pending']:
                scan_id = metadata.get('scan_id')
                if scan_id:
                    failed_scans.append(scan_id)
        except Exception as e:
            print(f"⚠️ Ошибка чтения {json_file}: {e}")
            continue

    if not failed_scans:
        print("✅ Нет сканов с ошибками для повторной отправки")
        return

    print(f"📊 Найдено сканов для повторной отправки: {len(failed_scans)}")

    success_count = 0
    for scan_id in failed_scans:
        if retry_specific_scan(scan_id):
            success_count += 1
        print("-" * 40)

    print(f"📊 Итоги повторной отправки:")
    print(f"  ✅ Успешно: {success_count}")
    print(f"  ❌ Неудачно: {len(failed_scans) - success_count}")

def list_failed_scans():
    """Показывает список сканов с ошибками"""
    storage_dir = get_storage_dir()
    json_files = glob.glob(os.path.join(storage_dir, "scan_*.json"))
    failed_scans = []

    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                metadata = json.load(f)

            status = metadata.get('status')
            if status == 'error':
                scan_id = metadata.get('scan_id')
                if scan_id:
                    failed_scans.append({
                        'scan_id': scan_id,
                        'error': metadata.get('upload_error', 'Unknown error'),
                        'json_file': json_file,
                        'attempts': metadata.get('upload_attempts', 0),
                        'last_attempt': metadata.get('last_upload_attempt', 'Never')
                    })
        except Exception as e:
            print(f"⚠️ Ошибка чтения {json_file}: {e}")
            continue

    if not failed_scans:
        print("✅ Нет сканов с ошибками")
        return

    print("❌ Сканы с ошибками отправки:")
    for i, scan in enumerate(failed_scans, 1):
        print(f"  {i}. {scan['scan_id']}")
        print(f"     📄 {scan['json_file']}")
        print(f"     ❌ {scan['error']}")
        print(f"     🔄 Попыток: {scan['attempts']}")
        print(f"     ⏰ Последняя попытка: {scan['last_attempt']}")
        print()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--all":
            retry_all_failed()
        elif sys.argv[1] == "--list":
            list_failed_scans()
        else:
            # Предполагаем что это scan_id
            scan_id = sys.argv[1]
            retry_specific_scan(scan_id)
    else:
        print("Использование:")
        print("  python3 retry_upload.py <scan_id>    # Повторно отправить конкретный скан")
        print("  python3 retry_upload.py --all        # Повторно отправить все сканы с ошибками")
        print("  python3 retry_upload.py --list       # Показать список сканов с ошибками")
