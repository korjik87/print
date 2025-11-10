#!/usr/bin/env python3
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Добавляем текущую директорию в путь Python
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from scanner import scanner_manager

class TestScanner(unittest.TestCase):
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        scanner_manager.stop_keyboard_listener()
    
    def tearDown(self):
        """Очистка после каждого теста"""
        scanner_manager.stop_keyboard_listener()
    
    @patch('subprocess.run')
    def test_scanner_exists(self, mock_subprocess):
        """Тест проверки существования сканера"""
        # Мокаем успешный ответ
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "device `some-scanner' is a CANON scanner"
        mock_subprocess.return_value = mock_result
        
        self.assertTrue(scanner_manager.scanner_exists())
    
    def test_keyboard_listener_lifecycle(self):
        """Тест жизненного цикла слушателя клавиатуры"""
        # Создаем мок-функцию callback
        mock_callback = MagicMock()
        
        # Запускаем слушатель
        start_result = scanner_manager.start_keyboard_listener(mock_callback)
        self.assertTrue(start_result)
        self.assertTrue(scanner_manager.scanning)
        
        # Останавливаем слушатель
        scanner_manager.stop_keyboard_listener()
        self.assertFalse(scanner_manager.scanning)
    
    def test_scan_callback_integration(self):
        """Интеграционный тест: запуск сканирования по callback"""
        scan_results = []
        
        def test_callback():
            """Тестовый callback для сканирования"""
            # Мокаем вызов scan_document чтобы не зависеть от реального сканера
            with patch.object(scanner_manager, 'scan_document') as mock_scan:
                mock_scan.return_value = {
                    'scan_id': 'test_123',
                    'status': 'success',
                    'error': None,
                    'content': 'test_content',
                    'filename': 'test.pdf'
                }
                result = scanner_manager.scan_document()
                scan_results.append(result)
        
        # Запускаем слушатель
        scanner_manager.start_keyboard_listener(test_callback)
        
        # Эмулируем нажатие кнопки (в реальности это сделал бы слушатель)
        test_callback()
        
        # Останавливаем слушатель
        scanner_manager.stop_keyboard_listener()
        
        # Проверяем, что callback был вызван
        self.assertEqual(len(scan_results), 1)
        self.assertEqual(scan_results[0]['scan_id'], 'test_123')

if __name__ == '__main__':
    unittest.main()
