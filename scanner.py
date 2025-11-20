import subprocess
import tempfile
import os
import base64
import uuid
import time
import select
import threading
import logging
import re
import json
from datetime import datetime

try:
    import evdev
    from evdev import ecodes, InputDevice, categorize
except ImportError:
    print("⚠️  evdev не установлен. Установите: pip install evdev")

import config
from utils import setup_logger

logger = setup_logger()

class ScanStorage:
    def __init__(self, storage_dir="scans_storage"):
        self.storage_dir = storage_dir
        self._ensure_storage_dir()

    def _ensure_storage_dir(self):
        """Создает директорию для хранения сканов, если она не существует"""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)
            # Создаем .gitignore чтобы не отслеживать сканы в git
            gitignore_path = os.path.join(self.storage_dir, ".gitignore")
            with open(gitignore_path, "w") as f:
                f.write("# Автоматически сгенерированные сканы\n")
                f.write("*.pdf\n")
                f.write("*.png\n")
                f.write("*.json\n")
                f.write("!README.md\n")
            logger.info(f"📁 Создана директория для хранения сканов: {self.storage_dir}")

    def save_scan(self, scan_result: dict) -> dict:
        """
        Сохраняет скан в директорию storage_dir
        Возвращает информацию о сохраненном файле
        """
        try:
            scan_id = scan_result["scan_id"]

            # Сохраняем файл скана
            file_extension = "pdf" if scan_result['filename'].endswith('.pdf') else 'png'
            scan_filename = f"scan_{scan_id}.{file_extension}"
            scan_path = os.path.join(self.storage_dir, scan_filename)

            # Декодируем base64 и сохраняем файл
            with open(scan_path, "wb") as f:
                file_content = base64.b64decode(scan_result["content"])
                f.write(file_content)

            # Сохраняем метаданные
            metadata = {
                "scan_id": scan_id,
                "filename": scan_filename,
                "original_filename": scan_result["filename"],
                "file_path": scan_path,
                "file_size": os.path.getsize(scan_path),
                "format": file_extension,
                "dpi": getattr(config, 'SCANNER_DPI', 300),
                "mode": getattr(config, 'SCANNER_MODE', 'Color'),
                "created_at": datetime.now().isoformat(),
                "status": "pending",  # pending, uploaded, error
                "upload_attempts": 0,
                "last_upload_attempt": None,
                "upload_error": None
            }

            metadata_filename = f"scan_{scan_id}.json"
            metadata_path = os.path.join(self.storage_dir, metadata_filename)

            with open(metadata_path, "w", encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(f"💾 Скан сохранен: {scan_path} ({metadata['file_size']} байт)")

            return {
                "status": "success",
                "scan_id": scan_id,
                "scan_path": scan_path,
                "metadata_path": metadata_path,
                "metadata": metadata
            }

        except Exception as e:
            logger.error(f"❌ Ошибка сохранения скана: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

class ScannerManager:
    def __init__(self):
        self.scanning = False
        self.keyboard_listener = None
        self.current_scan_callback = None

        # Защита от множественного запуска
        self.scan_in_progress = False
        self.last_scan_time = 0
        self.scan_cooldown = 3

        # Хранилище сканов
        self.storage = ScanStorage()

        # Кеш для данных сканера
        self._scanner_cache = None
        self._scanner_cache_time = 0
        self._scanner_cache_ttl = 900

        # Кеш для доступных сканеров
        self._available_scanners_cache = None
        self._available_scanners_cache_time = 0

    def _get_scanner_cache(self):
        """Получает кешированные данные сканера, если они еще актуальны"""
        if (self._scanner_cache and
            time.time() - self._scanner_cache_time < self._scanner_cache_ttl):
            return self._scanner_cache
        return None

    def _set_scanner_cache(self, value):
        """Устанавливает кеш сканера"""
        self._scanner_cache = value
        self._scanner_cache_time = time.time()

    def can_start_scan(self):
        """Проверяет, можно ли начать новое сканирование"""
        if self.scan_in_progress:
            logger.debug("⏳ Сканирование уже выполняется, пропускаем")
            return False

        current_time = time.time()
        if current_time - self.last_scan_time < self.scan_cooldown:
            logger.debug("⏳ Сканирование было недавно, пропускаем")
            return False

        return True

    def scanner_exists(self) -> bool:
        """Проверяет, доступен ли указанный в конфиге сканер (с кешированием)"""
        cached_result = self._get_scanner_cache()
        if cached_result is not None:
            logger.debug("✅ Используем кешированные данные сканера")
            return cached_result

        try:
            result = subprocess.run(
                ["scanimage", "-L"],
                capture_output=True,
                text=True,
                timeout=50
            )

            scanner_available = False
            if result.returncode == 0:
                if hasattr(config, 'SCANNER_DEVICE') and config.SCANNER_DEVICE:
                    scanner_available = config.SCANNER_DEVICE in result.stdout
                else:
                    scanner_available = bool(result.stdout.strip())

            # Кешируем результат
            self._set_scanner_cache(scanner_available)

            if scanner_available:
                logger.info("✅ Сканер доступен (данные закешированы)")
            else:
                logger.warning("❌ Сканер недоступен")

            return scanner_available

        except subprocess.TimeoutExpired:
            logger.error("❌ Таймаут при проверке сканера")
            # Не кешируем при ошибке таймаута
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка при проверке сканера: {e}")
            return False

    def get_available_scanners(self):
        """Получает список доступных сканеров (с кешированием)"""
        # Используем кеш, если он есть и не старше 5 минут
        if (self._available_scanners_cache and
            time.time() - self._available_scanners_cache_time < 300):
            logger.debug("✅ Используем кешированный список сканеров")
            return self._available_scanners_cache

        try:
            result = subprocess.run(
                ["scanimage", "-L"],
                capture_output=True,
                text=True,
                timeout=50
            )

            scanners = []
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.strip():
                        scanners.append(line.strip())

            # Кешируем результат
            self._available_scanners_cache = scanners
            self._available_scanners_cache_time = time.time()

            logger.info(f"✅ Получен список сканеров ({len(scanners)} шт.), данные закешированы")
            return scanners

        except subprocess.TimeoutExpired:
            logger.error("❌ Таймаут при получении списка сканеров")
            # Возвращаем кеш, даже если старый, при таймауте
            return self._available_scanners_cache or []
        except Exception as e:
            logger.error(f"❌ Ошибка при получении списка сканеров: {e}")
            return self._available_scanners_cache or []

    def get_scanner_device(self):
        """Возвращает устройство сканера для использования (с кешированием)"""
        # Используем кешированные данные о доступности
        if not self.scanner_exists():
            return None

        scanners = self.get_available_scanners()
        if not scanners:
            return None

        if hasattr(config, 'SCANNER_DEVICE') and config.SCANNER_DEVICE:
            # Ищем точное совпадение
            for scanner in scanners:
                if config.SCANNER_DEVICE in scanner:
                    device_match = re.search(r"device `([^']+)'", scanner)
                    if device_match:
                        device_id = device_match.group(1)
                        logger.info(f"✅ Найден сканер: {device_id}")
                        return device_id

        # Если точного совпадения нет, используем первый доступный
        if scanners:
            device_match = re.search(r"device `([^']+)'", scanners[0])
            if device_match:
                device_id = device_match.group(1)
                logger.info(f"✅ Используем первый доступный сканер: {device_id}")
                return device_id

        return None

    def scan_document(self, format_type=None, dpi=None, mode=None, use_adf=False) -> dict:
        """
        Выполняет сканирование документа с опциональной поддержкой автоподатчика
        Возвращает результат с информацией о количестве страниц
        """
        if format_type is None:
            format_type = config.SCANNER_FORMAT
        if dpi is None:
            dpi = config.SCANNER_DPI
        if mode is None:
            mode = config.SCANNER_MODE

        result = {
            "scan_id": str(uuid.uuid4()),
            "status": "success",
            "error": None,
            "content": None,
            "filename": None,
            "pages": 1,  # По умолчанию 1 страница
            "scan_type": "flatbed",
            "format": format_type.lower(),
            "file_size": 0
        }

        if getattr(config, 'DISABLE_SCAN', False):
            logger.info("Сканирование отключено (режим отладки)")
            result["log_status"] = "debug"
            return result

        # Устанавливаем флаг выполнения сканирования
        self.scan_in_progress = True
        self.last_scan_time = time.time()

        tmp_path = None
        tmp_files_to_cleanup = []  # Список файлов для очистки

        try:
            logger.info(f"🔍 Начинаем сканирование (ID: {result['scan_id']})")
            if use_adf:
                logger.info("📄 Используем автоподатчик документов")
                result["scan_type"] = "adf"

            # Проверяем доступность сканера (использует кеш)
            if not self.scanner_exists():
                available_scanners = self.get_available_scanners()
                error_msg = (
                    f"Сканер не найден в системе. "
                    f"Доступные сканеры: {len(available_scanners)}"
                )
                logger.error(error_msg)
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            # Получаем устройство сканера (использует кеш)
            scanner_device = self.get_scanner_device()
            if not scanner_device:
                error_msg = "Не удалось определить устройство сканера"
                logger.error(error_msg)
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            logger.info(f"🎯 Используем сканер: {scanner_device}")

            # ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА: Пытаемся разбудить сканер перед началом сканирования
            if not self._check_scanner_ready(scanner_device):
                logger.warning("😴 Сканер не отвечает. Пытаемся разбудить...")
                if not self._wake_up_scanner_advanced(scanner_device):
                    error_msg = "Не удалось разбудить сканер. Проверьте питание и подключение."
                    logger.error(f"❌ {error_msg}")
                    result.update({
                        "status": "error",
                        "error": error_msg
                    })
                    return result
                logger.info("✅ Сканер разбужен, продолжаем сканирование...")

            # Базовые параметры сканирования
            scan_args = [
                "scanimage",
                f"--device-name={scanner_device}",
                f"--resolution={dpi}",
                f"--mode={mode}",
            ]

            # Обработка ADF и формата
            if use_adf:
                # Для ADF используем только PDF формат (как показали тесты)
                effective_format = "pdf"
                filename = f"scan_{result['scan_id']}.pdf"
                tmp_path = os.path.join(tempfile.gettempdir(), filename)

                scan_args.extend([
                    "--source=ADF",
                    "--format=pdf",
                    f"--output-file={tmp_path}"
                ])

                # Добавляем дополнительные опции ADF из конфига если есть
                if hasattr(config, 'SCANNER_ADF_OPTIONS'):
                    scan_args.extend(config.SCANNER_ADF_OPTIONS)
                    logger.info(f"🔧 Используем опции автоподатчика: {config.SCANNER_ADF_OPTIONS}")

            else:
                # Обычное сканирование - используем запрошенный формат
                effective_format = format_type.lower()
                file_extension = "pdf" if effective_format == "pdf" else "png"
                filename = f"scan_{result['scan_id']}.{file_extension}"
                tmp_path = os.path.join(tempfile.gettempdir(), filename)

                scan_args.extend([
                    f"--format={effective_format}",
                    f"--output-file={tmp_path}"
                ])

            logger.info(f"📸 Выполняем сканирование...")
            logger.debug(f"Параметры: {' '.join(scan_args)}")

            # Выполняем сканирование с возможностью пробуждения сканера
            max_retries = 2
            retry_count = 0
            scan_successful = False

            while retry_count <= max_retries and not scan_successful:
                try:
                    scan_result = subprocess.run(
                        scan_args,
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 минут для ADF
                    )

                    # Если сканирование завершилось без ошибок кода возврата
                    if scan_result.returncode == 0:
                        scan_successful = True
                        break

                    # Обрабатываем ошибки
                    error_msg = scan_result.stderr.strip()

                    # Игнорируем ошибку "Document feeder out of documents" - это нормально для ADF
                    if use_adf and "Document feeder out of documents" in error_msg:
                        logger.info("📄 Автоподатчик: все документы отсканированы")
                        scan_successful = True
                        break

                    # Если это первая попытка и есть признаки "спящего" сканера, пробуем разбудить
                    if retry_count == 0 and self._is_scanner_sleep_error(error_msg):
                        logger.warning("😴 Сканер, возможно, в спящем режиме. Пытаемся разбудить...")
                        if self._wake_up_scanner_advanced(scanner_device):
                            retry_count += 1
                            time.sleep(8)  # Даем больше времени сканеру проснуться
                            continue
                        else:
                            logger.error("❌ Не удалось разбудить сканер")

                    # Другие ошибки - прерываем
                    logger.error(f"❌ Ошибка сканирования: {error_msg}")
                    result.update({
                        "status": "error",
                        "error": f"Ошибка сканирования: {error_msg}"
                    })
                    return result

                except subprocess.TimeoutExpired:
                    if retry_count == 0:
                        logger.warning("⏰ Таймаут сканирования. Пытаемся разбудить сканер...")
                        if self._wake_up_scanner_advanced(scanner_device):
                            retry_count += 1
                            time.sleep(8)
                            continue
                        else:
                            error_msg = "Не удалось разбудить сканер после таймаута"
                            logger.error(f"❌ {error_msg}")
                            result.update({
                                "status": "error",
                                "error": error_msg
                            })
                            return result
                    else:
                        error_msg = "Таймаут сканирования после попытки пробуждения"
                        logger.error(f"❌ {error_msg}")
                        result.update({
                            "status": "error",
                            "error": error_msg
                        })
                        return result

            # Если после всех попыток сканирование не удалось
            if not scan_successful:
                error_msg = "Сканирование не удалось после нескольких попыток"
                logger.error(f"❌ {error_msg}")
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            # Проверяем, что файл создан
            if not os.path.exists(tmp_path):
                error_msg = "Сканирование завершилось, но файл не создан"
                logger.error(f"❌ {error_msg}")
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            file_size = os.path.getsize(tmp_path)
            result["file_size"] = file_size

            # Проверяем, что файл не пустой и имеет минимальный размер
            min_file_size = 500  # Минимальный размер файла в байтах
            if file_size <= min_file_size:
                error_msg = f"Сканирование завершилось, но файл слишком маленький ({file_size} байт) - возможно, автоподатчик пуст"
                logger.error(f"❌ {error_msg}")
                result.update({
                    "status": "error",
                    "error": error_msg
                })
                return result

            logger.info(f"💾 Отсканированный файл сохранен: {tmp_path} ({file_size} байт)")

            # Подсчет страниц для PDF файлов
            if effective_format == "pdf":
                page_count = self._count_pdf_pages(tmp_path, file_size)
                result["pages"] = page_count

                if use_adf:
                    if page_count == 0:
                        logger.warning("⚠️ PDF создан, но не содержит страниц")
                    else:
                        logger.info(f"📄 Обнаружено страниц в PDF: {page_count}")
                else:
                    logger.info(f"📄 Страниц в PDF: {page_count}")

            # Читаем файл и кодируем в base64
            with open(tmp_path, "rb") as f:
                file_content = f.read()
                result["content"] = base64.b64encode(file_content).decode('utf-8')
                result["filename"] = filename

            logger.info(f"✅ Сканирование {result['scan_id']} успешно завершено")
            if use_adf:
                logger.info(f"📊 Итоги ADF сканирования: {result['pages']} страниц, {file_size} байт")
            else:
                logger.info(f"📊 Итоги сканирования: {result['pages']} страниц, {file_size} байт")

            return result

        except Exception as e:
            error_msg = f"Критическая ошибка сканирования: {str(e)}"
            logger.error(f"❌ {error_msg}")
            result.update({
                "status": "error",
                "error": error_msg
            })
            return result
        finally:
            # Сбрасываем флаг выполнения сканирования
            self.scan_in_progress = False

            # Удаляем временные файлы
            files_to_clean = []
            if tmp_path and os.path.exists(tmp_path):
                files_to_clean.append(tmp_path)

            # Добавляем любые другие временные файлы
            files_to_clean.extend(tmp_files_to_cleanup)

            for file_path in files_to_clean:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.debug(f"🧹 Временный файл удален: {file_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось удалить временный файл {file_path}: {e}")

    def _check_scanner_ready(self, scanner_device):
        """
        Проверяет, готов ли сканер к работе, отправляя тестовую команду
        """
        try:
            # Простая команда для проверки доступности сканера
            test_cmd = ["scanimage", f"--device-name={scanner_device}", "--help"]
            result = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
            return False

    def _is_scanner_sleep_error(self, error_msg):
        """
        Определяет, является ли ошибка признаком спящего режима сканера
        """
        sleep_indicators = [
            "device busy",
            "invalid argument",
            "no device found",
            "device not ready",
            "timeout",
            "no data available",
            "operation not supported",
            "io error",
            "broken pipe",
            "connection refused",
            "network is unreachable",
            "host is down",
            "no route to host",
            "connection timed out",
            "device or resource busy",
            "permission denied",
            "scanimage: open of device",
            "failed: Error during device I/O",
            "sane_start: Error during device I/O",
            "failed to start scanner",
            "scanner not ready",
            "warmup",
            "warming up",
            "offline",
            "sleep",
            "standby"
        ]

        error_lower = error_msg.lower()
        for indicator in sleep_indicators:
            if indicator in error_lower:
                logger.debug(f"🔍 Обнаружен признак спящего режима: '{indicator}' в ошибке: {error_msg}")
                return True
        return False

    def _wake_up_scanner_advanced(self, scanner_device):
        """
        Пытается "разбудить" сканер, используя расширенные методы
        Возвращает True если сканер удалось разбудить
        """
        logger.info(f"🔔 Пытаемся разбудить сканер: {scanner_device}")

        wake_up_methods = [
            # Метод 1: Простой запрос информации о сканере
            {"cmd": ["scanimage", f"--device-name={scanner_device}", "--help"], "desc": "запрос справки"},

            # Метод 2: Запрос доступных опций
            {"cmd": ["scanimage", f"--device-name={scanner_device}", "-A"], "desc": "запрос опций"},

            # Метод 4: Перезапрос списка сканеров
            {"cmd": ["scanimage", "-L"], "desc": "обновление списка сканеров"},

            # Метод 5: Для сетевых сканеров - попытка ping (если это сетевой сканер)
            {"cmd": ["ping", "-c", "2", scanner_device.split(':')[1] if ':' in scanner_device else scanner_device], "desc": "ping сетевого сканера"},

            # Метод 6: Проверка состояния через SANE
            {"cmd": ["scanimage", "--test"], "desc": "тест SANE"},

            # Метод 7: Для USB сканеров - перечисление USB устройств
            {"cmd": ["lsusb"], "desc": "проверка USB устройств"}
        ]

        success_count = 0
        total_methods = len(wake_up_methods)

        for i, method in enumerate(wake_up_methods, 1):
            try:
                logger.debug(f"🔧 Метод пробуждения {i}/{total_methods}: {method['desc']}")
                result = subprocess.run(
                    method["cmd"],
                    capture_output=True,
                    text=True,
                    timeout=15
                )

                if result.returncode == 0:
                    logger.info(f"✅ Метод пробуждения '{method['desc']}' выполнен успешно")
                    success_count += 1
                else:
                    logger.debug(f"⚠️ Метод пробуждения '{method['desc']}' завершился с кодом {result.returncode}")

            except subprocess.TimeoutExpired:
                logger.debug(f"⏰ Таймаут метода пробуждения '{method['desc']}'")
            except Exception as e:
                logger.debug(f"⚠️ Ошибка метода пробуждения '{method['desc']}': {e}")

        # Очищаем временный файл если он был создан
        wakeup_file = "/tmp/wakeup_test.png"
        if os.path.exists(wakeup_file):
            try:
                os.remove(wakeup_file)
            except:
                pass

        # Считаем сканер разбуженным если хотя бы некоторые методы сработали
        if success_count >= 2:
            logger.info(f"✅ Сканер успешно разбужен ({success_count}/{total_methods} методов сработало)")
            return True
        elif success_count > 0:
            logger.warning(f"⚠️ Сканер частично отвечает ({success_count}/{total_methods} методов сработало)")
            return True
        else:
            logger.error(f"❌ Не удалось разбудить сканер (0/{total_methods} методов сработало)")
            return False

    def _count_pdf_pages(self, pdf_path, file_size):
        """
        Подсчитывает количество страниц в PDF файле с улучшенной обработкой ошибок
        """
        # Если файл слишком маленький, вероятно он пустой или битый
        if file_size < 1000:
            logger.warning(f"⚠️ Файл PDF слишком маленький ({file_size} байт), вероятно пустой")
            return 0

        methods_tried = []

        # Метод 1: Используем pdfinfo (poppler-utils)
        try:
            result = subprocess.run(
                ["pdfinfo", pdf_path],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if line.startswith("Pages:"):
                        pages = int(line.split(":")[1].strip())
                        methods_tried.append(f"pdfinfo: {pages}")
                        return pages
            else:
                methods_tried.append("pdfinfo: failed")
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, subprocess.SubprocessError) as e:
            methods_tried.append(f"pdfinfo: error ({str(e)})")

        # Метод 2: Используем PyPDF2
        try:
            import PyPDF2
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                pages = len(reader.pages)
                methods_tried.append(f"PyPDF2: {pages}")
                return pages
        except ImportError:
            methods_tried.append("PyPDF2: not installed")
        except Exception as e:
            methods_tried.append(f"PyPDF2: error ({str(e)})")

        # Метод 3: Используем pypdf (новое название PyPDF2)
        try:
            import pypdf
            with open(pdf_path, 'rb') as f:
                reader = pypdf.PdfReader(f)
                pages = len(reader.pages)
                methods_tried.append(f"pypdf: {pages}")
                return pages
        except ImportError:
            methods_tried.append("pypdf: not installed")
        except Exception as e:
            methods_tried.append(f"pypdf: error ({str(e)})")

        # Метод 4: Простая проверка путем поиска ключевых слов в бинарном файле
        try:
            with open(pdf_path, 'rb') as f:
                content = f.read()

            # Ищем количество вхождений /Type/Page - грубая оценка количества страниц
            page_count = content.count(b'/Type/Page')
            if page_count > 0:
                methods_tried.append(f"binary_scan: {page_count}")
                return page_count

            # Ищем /Count - может содержать количество страниц
            import re
            count_match = re.search(rb'/Count\s+(\d+)', content)
            if count_match:
                count = int(count_match.group(1))
                methods_tried.append(f"count_scan: {count}")
                return count

        except Exception as e:
            methods_tried.append(f"binary_scan: error ({str(e)})")

        # Если все методы не сработали
        logger.warning(f"⚠️ Все методы подсчета страниц не сработали: {', '.join(methods_tried)}")

        # Эвристика: если файл больше 50KB, вероятно содержит хотя бы 1 страницу
        if file_size > 50000:
            logger.info("📄 Файл большого размера, предполагаем 1 страницу")
            return 1
        else:
            logger.warning("⚠️ Не удалось определить количество страниц, считаем 0")
            return 0

        except Exception as e:
            methods_tried.append(f"binary_scan: error ({str(e)})")

        # Если все методы не сработали
        logger.warning(f"⚠️ Все методы подсчета страниц не сработали: {', '.join(methods_tried)}")

        # Эвристика: если файл больше 50KB, вероятно содержит хотя бы 1 страницу
        if file_size > 50000:
            logger.info("📄 Файл большого размера, предполагаем 1 страницу")
            return 1
        else:
            logger.warning("⚠️ Не удалось определить количество страниц, считаем 0")
            return 0


    def find_keyboard_device(self):
        """Находит устройство ввода указанное в конфиге"""
        try:
            if hasattr(config, 'KEYBOARD_DEVICE') and config.KEYBOARD_DEVICE:
                if os.path.exists(config.KEYBOARD_DEVICE):
                    device = InputDevice(config.KEYBOARD_DEVICE)
                    logger.info(f"🎹 Используем устройство: {device.name} ({device.path})")

                    # Проверяем доступные кнопки
                    caps = device.capabilities()
                    if ecodes.EV_KEY in caps:
                        keys = caps[ecodes.EV_KEY]
                        available_trigger_keys = []
                        for key_name in getattr(config, 'SCAN_TRIGGER_KEYS', []):
                            key_code = getattr(ecodes, key_name, None)
                            if key_code and key_code in keys:
                                available_trigger_keys.append(key_name)

                        if available_trigger_keys:
                            logger.info(f"🎯 Доступные кнопки для сканирования: {', '.join(available_trigger_keys)}")

                    return device
                else:
                    logger.warning(f"⚠️ Устройство {config.KEYBOARD_DEVICE} не найдено")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при поиске устройства: {e}")
            return None

    def is_trigger_key(self, key_event):
        """Проверяет, является ли нажатая кнопка триггером для сканирования"""
        key_name = key_event.keycode
        trigger_keys = getattr(config, 'SCAN_TRIGGER_KEYS', [
            'KEY_ENTER', 'KEY_SPACE', 'KEY_POWER', 'KEY_1'
        ])

        is_trigger = key_name in trigger_keys
        logger.debug(f"🔍 Проверка кнопки {key_name}: {'триггер' if is_trigger else 'не триггер'}")

        return is_trigger

    def keyboard_listener_worker(self, callback):
        """Рабочий процесс для прослушивания нажатий кнопок"""
        device = None

        logger.info("🎹 Запускаем рабочий процесс слушателя клавиатуры...")

        while self.scanning:
            try:
                if device is None:
                    device = self.find_keyboard_device()
                    if device is None:
                        logger.warning("⚠️ Устройство ввода не найдено, повторная попытка через 5 секунд...")
                        time.sleep(5)
                        continue

                    logger.info(f"🎹 Устройство найдено: {device.name}")

                # Читаем события с устройства
                for event in device.read_loop():
                    if not self.scanning:
                        logger.info("🛑 Слушатель остановлен")
                        break

                    # Обрабатываем только события клавиш
                    if event.type == ecodes.EV_KEY:
                        try:
                            key_event = categorize(event)
                            key_name = key_event.keycode

                            # Обрабатываем как нажатия (1), так и удерживания (2)
                            if event.value in [1, 2]:
                                logger.info(f"🔘 Нажата кнопка: {key_name}")

                                if self.is_trigger_key(key_event):
                                    # Проверяем, можно ли начать сканирование
                                    if self.can_start_scan():
                                        logger.info(f"🎯 ТРИГГЕР! Запускаем сканирование")
                                        callback()
                                    else:
                                        logger.debug("⏳ Сканирование уже выполняется или недавно было, пропускаем")
                                else:
                                    logger.debug(f"❌ Кнопка {key_name} не в списке триггеров")

                        except Exception as e:
                            logger.error(f"❌ Ошибка обработки события клавиши: {e}")

            except Exception as e:
                logger.error(f"❌ Ошибка в слушателе устройства: {e}")
                device = None
                time.sleep(2)

    def start_keyboard_listener(self, scan_callback):
        """Запускает прослушивание нажатий кнопок"""
        if self.scanning:
            logger.warning("⚠️ Слушатель уже запущен")
            return False

        logger.info("🎹 Запускаем слушатель устройства ввода...")
        self.scanning = True
        self.current_scan_callback = scan_callback

        self.keyboard_listener = threading.Thread(
            target=self.keyboard_listener_worker,
            args=(scan_callback,),
            daemon=True
        )
        self.keyboard_listener.start()
        logger.info("✅ Слушатель устройства запущен")
        return True

    def stop_keyboard_listener(self):
        """Останавливает прослушивание нажатий кнопок"""
        logger.info("🛑 Останавливаем слушатель устройства...")
        self.scanning = False
        self.current_scan_callback = None

        if self.keyboard_listener and self.keyboard_listener.is_alive():
            self.keyboard_listener.join(timeout=5)
        logger.info("✅ Слушатель устройства остановлен")

# Глобальный экземпляр менеджера сканера
scanner_manager = ScannerManager()
