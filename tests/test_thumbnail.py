import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import MainWindow, PinWindow
from pin_session import load_session, save_session


class ThumbnailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def image(self):
        image = QPixmap(1200, 600)
        image.fill('red')
        image.setDevicePixelRatio(2)
        return image

    def test_shift_double_click_preserves_scale_position_and_original(self):
        pin = PinWindow(self.image(), QPoint(40, 50))
        try:
            pin.scale = 1.5
            pin.resize_image()
            pin.show()
            full_size = pin.size()
            QTest.mouseDClick(pin, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(15, 15))
            self.assertTrue(pin.thumbnail)
            self.assertEqual(pin.size().toTuple(), (162, 82))
            self.assertEqual(pin.scale, 1.5)
            pin.copy_image()
            self.assertEqual(self.app.clipboard().pixmap().size(), self.image().size())
            results = []
            pin.ocr_requested.connect(results.append)
            pin.extract_text()
            self.assertEqual(results[0].size(), self.image().size())
            event = QWheelEvent(QPointF(10, 10), QPointF(50, 60), QPoint(), QPoint(0, 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            pin.wheelEvent(event)
            self.assertEqual(pin.scale, 1.5)
            pin.move(90, 100)
            pin.toggle_thumbnail()
            self.assertEqual(pin.size(), full_size)
            self.assertEqual(pin.pos(), QPoint(90, 100))
            pin.toggle_thumbnail()
            pin.reset_size()
            self.assertFalse(pin.thumbnail)
            self.assertEqual(pin.scale, 1)
        finally:
            pin.close_without_confirmation()
            self.app.processEvents()

    def test_lock_blocks_toggle_and_small_image_is_not_enlarged(self):
        image = QPixmap(60, 30)
        image.fill('blue')
        pin = PinWindow(image, QPoint())
        try:
            size = pin.size()
            pin.toggle_thumbnail()
            self.assertEqual(pin.size(), size)
            pin.toggle_lock()
            pin.toggle_thumbnail()
            self.assertTrue(pin.thumbnail)
            pin.set_border_width(5)
            self.assertEqual(pin.size().toTuple(), (70, 40))
        finally:
            pin.close_without_confirmation()

    def test_history_and_restart_preserve_thumbnail_and_old_sessions_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'test.ini')
            first = MainWindow(False, QSettings(path, QSettings.IniFormat))
            first.restore_pins = True
            pin = first.add_pin(self.image(), QPoint(50, 50))
            pin.scale = 2
            pin.toggle_thumbnail()
            pin.toggle_lock()
            pin.close_without_confirmation()
            first.restore_closed_pin()
            restored = first.pins[0]
            self.assertTrue(restored.thumbnail)
            self.assertTrue(restored.locked)
            self.assertEqual(restored.scale, 2)
            first.cleanup()
            second = MainWindow(False, QSettings(path, QSettings.IniFormat))
            second.restore_pins = True
            second.restore_session()
            self.assertTrue(second.pins[0].thumbnail)
            self.assertTrue(second.pins[0].locked)
            self.assertEqual(second.pins[0].size().toTuple(), (162, 82))
            old = json.loads(first.session_path.read_text(encoding='utf-8'))
            del old['pins'][0]['thumbnail']
            first.session_path.write_text(json.dumps(old), encoding='utf-8')
            self.assertFalse(load_session(first.session_path)[0][5])
            second.cleanup()
            first.close()
            second.close()
            self.app.processEvents()
