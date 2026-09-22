import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from main import MainWindow
from pin_session import load_session


class CloseConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.window = MainWindow(False, QSettings(str(Path(self.directory.name)/'test.ini'), QSettings.IniFormat))
        image = QPixmap(80, 40)
        image.fill('red')
        self.pin = self.window.add_pin(image, QPoint(30, 30))

    def tearDown(self):
        self.window.cleanup()
        self.window.close()
        self.app.processEvents()
        self.directory.cleanup()

    def test_escape_cancels_prompt_and_accept_records_history(self):
        observed = []
        def dismiss():
            prompt = self.pin.close_prompt
            observed.append(prompt.defaultButton() == prompt.button(QMessageBox.StandardButton.No))
            QTest.keyClick(prompt, Qt.Key.Key_Escape)
        QTimer.singleShot(0, dismiss)
        self.pin.close()
        self.assertEqual(observed, [True])
        self.assertTrue(self.pin.isVisible())
        self.assertEqual(self.window.closed_pins, [])
        self.pin.activateWindow()
        self.pin.setFocus()
        self.app.processEvents()
        QTimer.singleShot(0, lambda: self.pin.close_prompt.button(QMessageBox.StandardButton.Yes).click())
        QTest.keyClick(self.pin, Qt.Key.Key_Escape)
        self.assertEqual(self.window.pins, [])
        self.assertEqual(len(self.window.closed_pins), 1)

    def test_bulk_cancel_and_confirm_once(self):
        self.window.add_pin(self.pin.pixmap, QPoint(100, 30))
        with patch('main.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as ask:
            self.window.close_pins()
            ask.assert_called_once()
        self.assertEqual(len(self.window.pins), 2)
        with patch('main.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes) as ask, patch('main.QMessageBox.exec') as individual:
            self.window.close_pins()
            ask.assert_called_once()
            individual.assert_not_called()
        self.assertEqual(len(self.window.closed_pins), 2)

    def test_shutdown_saves_without_prompt(self):
        self.window.restore_pins = True
        with patch('main.QMessageBox.exec') as individual, patch('main.QMessageBox.question') as bulk:
            self.window.cleanup()
            individual.assert_not_called()
            bulk.assert_not_called()
        self.assertEqual(len(load_session(self.window.session_path)), 1)
        self.assertEqual(self.window.closed_pins, [])

    def test_shutdown_during_close_prompt(self):
        self.window.restore_pins = True
        QTimer.singleShot(0, self.window.cleanup)
        self.pin.close()
        self.assertTrue(self.window.quitting)
        self.assertEqual(self.window.pins, [])
        self.assertEqual(len(load_session(self.window.session_path)), 1)
