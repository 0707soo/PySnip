import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox
import uuid
from unittest.mock import patch
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import QApplication
from main import MainWindow
from hotkeys import SettingsDialog
from ocr_ui import OcrDialog
from single_instance import SingleInstance


class NewFeatureTests(unittest.TestCase):
    def setUp(self):
        for method in ('exec', 'question'):
            mock = patch('main.QMessageBox.' + method, return_value=QMessageBox.StandardButton.Yes)
            mock.start()
            self.addCleanup(mock.stop)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_instance_notification_and_restart(self):
        identity = 'PySnip-test-' + uuid.uuid4().hex
        first = SingleInstance(identity)
        self.assertTrue(first.acquire())
        received = []
        first.activated.connect(lambda: received.append(True))
        code = ('from single_instance import SingleInstance; '
                f's=SingleInstance({identity!r}); '
                'assert not s.acquire(); assert s.notify()')
        try:
            subprocess.run([sys.executable, '-c', code], check=True, timeout=10)
            self.app.processEvents()
            self.assertEqual(received, [True])
        finally:
            first.close()
        second = SingleInstance(identity)
        self.assertTrue(second.acquire())
        second.close()

    def test_instance_recovers_after_process_crash(self):
        identity = 'PySnip-test-' + uuid.uuid4().hex
        code = ('import os; from single_instance import SingleInstance; '
                f's=SingleInstance({identity!r}); assert s.acquire(); os._exit(0)')
        subprocess.run([sys.executable, '-c', code], check=True, timeout=10)
        instance = SingleInstance(identity)
        try:
            self.assertTrue(instance.acquire())
        finally:
            instance.close()

    def test_pins_hide_restore_and_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(False, QSettings(str(Path(tmp)/'config.ini'), QSettings.IniFormat))
            try:
                image = QPixmap(80, 40)
                image.fill()
                pins = [window.add_pin(image, QPoint(100+i*100, 100)) for i in range(3)]
                pins[0].scale = 2
                pins[0].resize_image()
                geometry = [pin.geometry() for pin in pins]
                window.toggle_pins()
                self.assertTrue(all(not pin.isVisible() for pin in pins))
                new = window.add_pin(image, QPoint(400, 100))
                self.assertFalse(new.isVisible())
                window.toggle_pins()
                self.assertTrue(all(pin.isVisible() for pin in window.pins))
                self.assertEqual([pin.geometry() for pin in pins], geometry)
                self.assertEqual(pins[0].scale, 2)
                window.toggle_pins()
                window.close_pins()
                self.assertEqual(window.pins, [])
                self.assertFalse(window.pins_hidden)
                self.assertFalse(window.toggle_button.isEnabled())
            finally:
                window.cleanup()
                window.close()

    def test_ocr_copy_setting_and_result_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'config.ini')
            window = MainWindow(False, QSettings(path, QSettings.IniFormat))
            dialog = OcrDialog(window, QImage(80, 40, QImage.Format_RGB32))
            try:
                self.assertFalse(window.ocr_auto_copy)
                self.app.clipboard().setText('original')
                dialog.show_text({'ok': True, 'text': 'inspect'})
                self.assertEqual(self.app.clipboard().text(), 'original')
                settings = SettingsDialog(window)
                settings.ocr_auto_copy.setChecked(True)
                settings.save()
                self.assertTrue(window.ocr_auto_copy)
                dialog.show_text({'ok': True, 'text': '한국어 English'})
                self.assertEqual(self.app.clipboard().text(), '한국어 English')
                for result in [{'ok': True, 'text': '  '}, {'ok': False, 'error': 'failed'}]:
                    dialog.show_text(result)
                    self.assertEqual(self.app.clipboard().text(), '한국어 English')
                dialog.stopping = True
                dialog.show_text({'ok': True, 'text': 'cancelled'})
                self.assertEqual(self.app.clipboard().text(), '한국어 English')
                loaded = MainWindow(False, QSettings(path, QSettings.IniFormat))
                self.assertTrue(loaded.ocr_auto_copy)
                self.assertEqual(loaded.bindings['toggle'], 'F2')
                loaded.cleanup()
                loaded.close()
                settings = SettingsDialog(window)
                settings.reset_defaults()
                self.assertFalse(settings.ocr_auto_copy.isChecked())
                settings.reject()
                self.assertTrue(window.ocr_auto_copy)
            finally:
                dialog.shutdown()
                window.cleanup()
                window.close()
