#!/usr/bin/env python3
import os
import json
import glob
import base64
from datetime import datetime

def find_scan_files():
    """Находит все файлы сканов в текущей директории"""
    print("🔍 Поиск файлов сканов...")
    print("=" * 60)

    # Ищем JSON файлы с метаданными
    json_files = glob.glob("scan_*.json")
    pdf_files = glob.glob("scan_*.pdf")
    png_files = glob.glob("scan_*.png")

    print("📁 JSON файлы с метаданными:")
    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                metadata = json.load(f)

            file_size = os.path.getsize(json_file)
            created_time = datetime.fromtimestamp(os.path.getctime(json_file))

            print(f"  📄 {json_file}")
            print(f"     📏 Размер: {file_size} байт")
            print(f"     🕐 Создан: {created_time}")
            print(f"     🆔 Scan ID: {metadata.get('scan_id', 'unknown')}")
            print(f"     📊 Статус: {metadata.get('upload_status', 'unknown')}")
            if metadata.get('upload_status') == 'error':
                print(f"     ❌ Ошибка: {metadata.get('upload_error', 'unknown')}")
            print()

        except Exception as e:
            print(f"  ❌ Ошибка чтения {json_file}: {e}")

    print("📊 PDF файлы:")
    for pdf_file in pdf_files:
        file_size = os.path.getsize(pdf_file)
        created_time = datetime.fromtimestamp(os.path.getctime(pdf_file))
        print(f"  📄 {pdf_file} ({file_size} байт, {created_time})")

    print("📊 PNG файлы:")
    for png_file in png_files:
        file_size = os.path.getsize(png_file)
        created_time = datetime.fromtimestamp(os.path.getctime(png_file))
        print(f"  🖼️  {png_file} ({file_size} байт, {created_time})")

    return json_files, pdf_files, png_files

def check_failed_uploads():
    """Проверяет файлы с ошибками отправки"""
    print("\n❌ Файлы с ошибками отправки:")
    print("=" * 60)

    json_files = glob.glob("scan_*.json")
    failed_files = []

    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                metadata = json.load(f)

            if metadata.get('upload_status') == 'error':
                failed_files.append({
                    'json_file': json_file,
                    'metadata': metadata
                })

                print(f"  📄 {json_file}")
                print(f"     🆔 Scan ID: {metadata.get('scan_id', 'unknown')}")
                print(f"     ❌ Ошибка: {metadata.get('upload_error', 'unknown')}")

                # Проверяем есть ли соответствующий файл
                scan_id = metadata.get('scan_id')
                if scan_id:
                    pdf_file = f"scan_backup_{scan_id}.pdf"
                    png_file = f"scan_backup_{scan_id}.png"

                    if os.path.exists(pdf_file):
                        print(f"     📄 Файл: {pdf_file}")
                    elif os.path.exists(png_file):
                        print(f"     🖼️  Файл: {png_file}")
                    else:
                        print(f"     ⚠️  Файл не найден")
                print()

        except Exception as e:
            print(f"  ❌ Ошибка чтения {json_file}: {e}")

    return failed_files

if __name__ == "__main__":
    json_files, pdf_files, png_files = find_scan_files()
    failed_files = check_failed_uploads()

    print(f"\n📊 Итого:")
    print(f"  📄 JSON файлов: {len(json_files)}")
    print(f"  📄 PDF файлов: {len(pdf_files)}")
    print(f"  🖼️  PNG файлов: {len(png_files)}")
    print(f"  ❌ Ошибок отправки: {len(failed_files)}")
