import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox
from pathlib import Path
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from main import MainWindow
from hotkeys import SettingsDialog
from pin_session import load_session


class SessionTests(unittest.TestCase):
    def setUp(self):
        for method in ('exec', 'question'):
            mock = patch('main.QMessageBox.' + method, return_value=QMessageBox.StandardButton.Yes)
            mock.start()
            self.addCleanup(mock.stop)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_restore_images_geometry_dpr_and_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = str(Path(tmp)/'PySnip.ini')
            def window():
                return MainWindow(False, QSettings(config, QSettings.IniFormat))
            first = window()
            self.assertFalse(first.restore_pins)
            settings = SettingsDialog(first)
            settings.restore_pins.setChecked(True)
            settings.save()
            image = QPixmap(100, 60)
            image.fill('red')
            image.setDevicePixelRatio(2)
            pin = first.add_pin(image, QPoint(40, 40))
            pin.scale = 1.5
            pin.resize_image()
            expected = pin.size()
            removed = first.add_pin(image, QPoint(80, 80))
            removed.close()
            first.toggle_pins()
            first.cleanup()
            first.close()
            second = window()
            second.restore_session()
            self.assertEqual(len(second.pins), 1)
            restored = second.pins[0]
            self.assertTrue(restored.isVisible())
            self.assertEqual(restored.pos(), QPoint(40, 40))
            self.assertEqual(restored.size(), expected)
            self.assertEqual(restored.pixmap.devicePixelRatio(), 2)
            self.assertEqual(restored.pixmap.toImage().pixelColor(0, 0).name(), '#ff0000')
            second.close_pins()
            second.cleanup()
            second.close()
            self.assertEqual(load_session(first.session_path), [])
            third = window()
            settings = SettingsDialog(third)
            settings.restore_pins.setChecked(False)
            settings.save()
            self.assertFalse(third.session_path.exists())
            third.cleanup()
            third.close()

    def test_corrupt_file_does_not_prevent_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp)/'PySnip.ini'), QSettings.IniFormat)
            settings.setValue('Session/restore_pins', True)
            window = MainWindow(False, settings)
            window.session_path.write_text('{invalid', encoding='utf-8')
            window.restore_session()
            self.assertEqual(window.pins, [])
            self.assertIn('복원 실패', window.status.text())
            window.cleanup()
            window.close()
