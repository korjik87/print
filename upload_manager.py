# upload_manager.py
#!/usr/bin/env python3
"""
Утилита для ручного управления загрузкой сканов.
"""

import os
import json
import glob
import sys
from upload_service import UploadService

def list_scans(status_filter=None):
    """Показывает список сканов с фильтром по статусу"""
    storage_dir = "scans_storage"
    scans = []

    pattern = os.path.join(storage_dir, "scan_*.json")
    for metadata_file in glob.glob(pattern):
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if status_filter is None or metadata.get('status') == status_filter:
                scans.append(metadata)
        except:
            continue

    if not scans:
        print("📭 Сканы не найдены")
        return

    print(f"📊 Найдено сканов: {len(scans)}")
    print("-" * 80)

    for scan in scans:
        status_icon = "✅" if scan.get('status') == 'uploaded' else "⏳" if scan.get('status') == 'pending' else "❌"
        print(f"{status_icon} {scan['scan_id']}")
        print(f"   📁 Файл: {scan['filename']}")
        print(f"   📅 Создан: {scan['created_at']}")
        print(f"   🔄 Попытки: {scan.get('upload_attempts', 0)}")

        if scan.get('status') == 'error':
            print(f"   ❌ Ошибка: {scan.get('upload_error', 'Unknown')}")

        if scan.get('uploaded_at'):
            print(f"   ✅ Загружен: {scan['uploaded_at']}")

        print()

def retry_failed():
    """Повторно пытается загрузить все сканы с ошибками"""
    service = UploadService()
    pending_scans = service.get_pending_scans()

    failed_scans = [scan for scan in pending_scans if scan['metadata'].get('status') == 'error']

    if not failed_scans:
        print("✅ Нет сканов с ошибками для повторной загрузки")
        return

    print(f"🔄 Повторная загрузка {len(failed_scans)} сканов с ошибками...")

    for scan_info in failed_scans:
        scan_id = scan_info['metadata']['scan_id']
        print(f"📤 Загрузка {scan_id}...")
        service.process_scan(scan_info)

    print("✅ Повторная загрузка завершена")

def cleanup_uploaded():
    """Удаляет уже загруженные сканы"""
    storage_dir = "scans_storage"
    removed_count = 0

    pattern = os.path.join(storage_dir, "scan_*.json")
    for metadata_file in glob.glob(pattern):
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            if metadata.get('status') == 'uploaded':
                # Удаляем файл скана
                scan_file = metadata['file_path']
                if os.path.exists(scan_file):
                    os.remove(scan_file)

                # Удаляем метаданные
                os.remove(metadata_file)

                removed_count += 1
                print(f"🧹 Удален: {metadata['scan_id']}")

        except Exception as e:
            print(f"❌ Ошибка удаления {metadata_file}: {e}")

    print(f"✅ Удалено загруженных сканов: {removed_count}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "list":
            status = sys.argv[2] if len(sys.argv) > 2 else None
            list_scans(status)
        elif command == "retry":
            retry_failed()
        elif command == "cleanup":
            cleanup_uploaded()
        elif command == "stats":
            list_scans()  # Показывает всю статистику
        else:
            print("❌ Неизвестная команда")
    else:
        print("Использование:")
        print("  python3 upload_manager.py list [status]    # Список сканов (all|pending|uploaded|error)")
        print("  python3 upload_manager.py retry            # Повторная загрузка сканов с ошибками")
        print("  python3 upload_manager.py cleanup          # Удаление загруженных сканов")
        print("  python3 upload_manager.py stats            # Статистика сканов")
