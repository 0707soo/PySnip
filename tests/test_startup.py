import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from main import MainWindow


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_first_launch_then_tray_and_manual_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'PySnip.ini')
            for first in (True, False):
                window = MainWindow(False, QSettings(path, QSettings.IniFormat))
                window.tray = Mock()
                window.tray.isVisible.return_value = True
                try:
                    with patch.object(window, 'restore_session') as restore:
                        window.start()
                        restore.assert_called_once()
                    self.assertEqual(window.isVisible(), first)
                    self.assertTrue(window.settings.value('Startup/has_started', type=bool))
                    window.activate_existing()
                    self.assertTrue(window.isVisible())
                finally:
                    window.cleanup()
                    window.close()

    def test_repeated_launch_without_tray_shows_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / 'PySnip.ini'), QSettings.IniFormat)
            settings.setValue('Startup/has_started', True)
            window = MainWindow(False, settings)
            try:
                window.start()
                self.assertTrue(window.isVisible())
            finally:
                window.cleanup()
                window.close()
