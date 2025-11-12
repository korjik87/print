#!/usr/bin/env python3
import os
import json
import glob
import base64
import sys
from scan_uploader import scan_uploader

def retry_specific_scan(scan_id):
    """Повторно отправляет конкретный скан по ID"""
    print(f"🔄 Повторная отправка скана {scan_id}...")

    # Ищем JSON файл
    json_file = f"scan_{scan_id}.json"
    if not os.path.exists(json_file):
        print(f"❌ Файл метаданных {json_file} не найден")
        return False

    # Ищем файл скана
    pdf_file = f"scan_backup_{scan_id}.pdf"
    png_file = f"scan_backup_{scan_id}.png"

    scan_file = None
    if os.path.exists(pdf_file):
        scan_file = pdf_file
    elif os.path.exists(png_file):
        scan_file = png_file
    else:
        print(f"❌ Файл скана для {scan_id} не найден")
        return False

    try:
        # Читаем метаданные
        with open(json_file, 'r') as f:
            metadata = json.load(f)

        # Читаем файл скана и кодируем в base64
        with open(scan_file, 'rb') as f:
            file_content = f.read()
            content_base64 = base64.b64encode(file_content).decode('utf-8')

        # Подготавливаем данные для отправки
        scan_result = {
            'scan_id': scan_id,
            'filename': metadata.get('filename', os.path.basename(scan_file)),
            'content': content_base64,
        }

        # Отправляем
        upload_result = scan_uploader.upload_scan(scan_result)

        if upload_result['upload_status'] == 'success':
            print(f"✅ Скан {scan_id} успешно отправлен!")

            # Обновляем метаданные
            metadata['upload_status'] = 'success'
            metadata['upload_error'] = None
            metadata['response_data'] = upload_result.get('response_data')

            with open(json_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            return True
        else:
            print(f"❌ Ошибка отправки: {upload_result['error']}")

            # Обновляем метаданные с новой ошибкой
            metadata['upload_status'] = 'error'
            metadata['upload_error'] = upload_result['error']

            with open(json_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            return False

    except Exception as e:
        print(f"❌ Ошибка при обработке скана {scan_id}: {e}")
        return False

def retry_all_failed():
    """Повторно отправляет все сканы с ошибками"""
    print("🔄 Повторная отправка всех сканов с ошибками...")

    json_files = glob.glob("scan_*.json")
    failed_scans = []

    # Находим сканы с ошибками
    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                metadata = json.load(f)

            if metadata.get('upload_status') == 'error':
                scan_id = metadata.get('scan_id')
                if scan_id:
                    failed_scans.append(scan_id)
        except:
            continue

    if not failed_scans:
        print("✅ Нет сканов с ошибками для повторной отправки")
        return

    print(f"📊 Найдено сканов с ошибками: {len(failed_scans)}")

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
    json_files = glob.glob("scan_*.json")
    failed_scans = []

    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                metadata = json.load(f)

            if metadata.get('upload_status') == 'error':
                scan_id = metadata.get('scan_id')
                if scan_id:
                    failed_scans.append({
                        'scan_id': scan_id,
                        'error': metadata.get('upload_error', 'Unknown error'),
                        'json_file': json_file
                    })
        except:
            continue

    if not failed_scans:
        print("✅ Нет сканов с ошибками")
        return

    print("❌ Сканы с ошибками отправки:")
    for i, scan in enumerate(failed_scans, 1):
        print(f"  {i}. {scan['scan_id']}")
        print(f"     📄 {scan['json_file']}")
        print(f"     ❌ {scan['error']}")
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
