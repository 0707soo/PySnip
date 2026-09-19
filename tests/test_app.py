import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import unittest
import tempfile
from pathlib import Path
from PySide6.QtCore import QPoint, QRect, Qt, QSettings
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import CaptureOverlay, MainWindow, crop_selection, drag_rect


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_crop_retains_physical_resolution_and_color(self):
        pixmap = QPixmap(300, 150)
        pixmap.fill(QColor('red'))
        pixmap.setDevicePixelRatio(1.5)
        result = crop_selection(pixmap, QRect(10, 10, 40, 20))
        self.assertEqual((result.width(), result.height()), (60, 30))
        self.assertEqual(result.devicePixelRatio(), 1.5)
        self.assertEqual(result.toImage().pixelColor(0, 0), QColor('red'))

    def test_reverse_drag_and_escape(self):
        screen = self.app.primaryScreen()
        image = QPixmap(screen.size())
        image.fill(QColor('blue'))
        overlay = CaptureOverlay(screen, image)
        results, cancelled = [], []
        overlay.selected.connect(lambda pix, pos: results.append(pix))
        overlay.cancelled.connect(lambda: cancelled.append(True))
        overlay.show()
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(20, 30))
        self.assertEqual((results[0].width(), results[0].height()), (80, 70))
        QTest.keyClick(overlay, Qt.Key.Key_Escape)
        self.assertEqual(cancelled, [True])
        overlay.close()

    def test_drag_directions_have_identical_bounds(self):
        bounds = QRect(0, 0, 200, 200)
        forward = drag_rect(QPoint(20, 30), QPoint(100, 100), bounds)
        backward = drag_rect(QPoint(100, 100), QPoint(20, 30), bounds)
        self.assertEqual(forward, backward)
        self.assertEqual(forward, QRect(20, 30, 80, 70))

    def test_capture_clipboard_and_pin_lifecycle(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = QSettings(str(Path(directory.name) / 'test.ini'), QSettings.Format.IniFormat)
        window = MainWindow(enable_integrations=False, settings=settings)
        image = QPixmap(80, 40)
        image.fill(QColor('green'))
        window.finish_capture(image, QPoint(10, 10))
        self.assertEqual(len(window.pins), 1)
        self.assertEqual(self.app.clipboard().pixmap().size(), image.size())
        pin = window.pins[0]
        pin.scale = 2
        pin.resize_image()
        self.assertEqual(pin.width(), 162)
        pin.copy_image()
        self.assertEqual(self.app.clipboard().pixmap().width(), 80)
        pin.reset_size()
        self.assertEqual(pin.width(), 82)
        window.close_pins()
        self.assertEqual(window.pins, [])
        window.deleteLater()


if __name__ == '__main__':
    unittest.main()
