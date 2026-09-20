import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import MainWindow, PinWindow
from hotkeys import SettingsDialog
from annotation_ui import AnnotationCanvas, AnnotationDialog, Mark, render_marks
from magnifier import magnified_patch
from pin_session import save_session, load_session


class EditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def tearDown(self):
        self.app.processEvents()

    def image(self):
        image = QPixmap(200, 120)
        image.fill('white')
        return image

    def test_history_unlimited_limit_order_restore_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'test.ini')
            window = MainWindow(False, QSettings(path, QSettings.IniFormat))
            try:
                self.assertEqual(window.history_limit, 0)
                for i in range(8):
                    pin = window.add_pin(self.image(), QPoint(20 + i, 30))
                    pin.scale = 1.5
                    pin.toggle_lock()
                    pin.close()
                self.assertEqual(len(window.closed_pins), 8)
                dialog = SettingsDialog(window)
                dialog.history_limit.setValue(2)
                dialog.save()
                self.assertEqual(len(window.closed_pins), 2)
                window.restore_closed_pin()
                restored = window.pins[-1]
                self.assertEqual(restored.pos(), QPoint(27, 30))
                self.assertEqual(restored.scale, 1.5)
                self.assertTrue(restored.locked)
                self.assertTrue(restored.isVisible())
                self.assertEqual(len(window.closed_pins), 1)
                window.restore_closed_pin()
                self.assertEqual(window.pins[-1].pos(), QPoint(26, 30))
                self.assertFalse(window.history_button.isEnabled())
                self.assertEqual(window.settings.value('History/limit', type=int), 2)
                cancelled = SettingsDialog(window)
                cancelled.reset_defaults()
                self.assertEqual(cancelled.history_limit.value(), 0)
                cancelled.reject()
                self.assertEqual(window.history_limit, 2)
                window.cleanup()
                self.assertEqual(window.closed_pins, [])
            finally:
                window.cleanup()
                window.close()

    def test_lock_prevents_drag_zoom_reset_and_survives_session(self):
        pin = PinWindow(self.image(), QPoint(60, 60))
        pin.scale = 2
        pin.resize_image()
        pin.show()
        pin.toggle_lock()
        original = pin.geometry()
        QTest.mousePress(pin, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        QTest.mouseMove(pin, QPoint(80, 60))
        QTest.mouseRelease(pin, Qt.MouseButton.LeftButton, pos=QPoint(80, 60))
        event = QWheelEvent(QPointF(20, 20), QPointF(80, 80), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        pin.wheelEvent(event)
        pin.reset_size()
        self.assertEqual(pin.geometry(), original)
        self.assertEqual(pin.scale, 2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            save_session(path, [pin])
            self.assertTrue(load_session(path)[0][-1])
        pin.toggle_lock()
        pin.wheelEvent(event)
        self.assertGreater(pin.scale, 2)
        pin.close()

    def test_magnifier_uses_physical_pixels_at_edges(self):
        image = QImage(100, 80, QImage.Format_RGB32)
        image.fill('white')
        image.setPixelColor(40, 30, QColor('red'))
        image.setPixelColor(0, 0, QColor('blue'))
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(2)
        patch = magnified_patch(pixmap, QPoint(20, 15)).toImage()
        self.assertEqual(patch.pixelColor(73, 73), QColor('red'))
        edge = magnified_patch(pixmap, QPoint()).toImage()
        self.assertEqual(edge.pixelColor(73, 73), QColor('blue'))
        self.assertEqual(edge.pixelColor(0, 0), QColor('#20242b'))
        self.assertEqual(pixmap.toImage().pixelColor(40, 30), QColor('red'))

    def test_annotation_rendering_undo_redo_and_original(self):
        canvas = AnnotationCanvas(self.image())
        canvas.commit(Mark('rectangle', QPointF(10, 10), QPointF(90, 70)))
        self.assertNotEqual(canvas.rendered.pixelColor(10, 20), QColor('white'))
        canvas.commit(Mark('arrow', QPointF(100, 90), QPointF(160, 90)))
        self.assertNotEqual(canvas.rendered.pixelColor(130, 90), QColor('white'))
        canvas.commit(Mark('text', QPointF(100, 10), QPointF(100, 10), text='한글 A'))
        edited = canvas.rendered.copy()
        canvas.undo()
        self.assertNotEqual(canvas.rendered, edited)
        canvas.redo()
        self.assertEqual(canvas.rendered, edited)
        canvas.undo()
        canvas.commit(Mark('rectangle', QPointF(3, 3), QPointF(6, 6)))
        self.assertEqual(canvas.redo_marks, [])
        self.assertEqual(canvas.original, self.image().toImage())
        canvas.close()

    def test_mosaic_flattens_only_selected_area(self):
        image = QImage(40, 40, QImage.Format_RGB32)
        for y in range(40):
            for x in range(40):
                image.setPixelColor(x, y, QColor('black' if x % 2 else 'white'))
        result = render_marks(image, [Mark('mosaic', QPointF(10, 10), QPointF(30, 30), block=10)])
        self.assertEqual(result.pixelColor(0, 0), image.pixelColor(0, 0))
        self.assertEqual(result.pixelColor(12, 12), result.pixelColor(13, 12))
        self.assertNotEqual(result.pixelColor(12, 12), image.pixelColor(12, 12))

    def test_canvas_coordinate_mapping_gestures_and_exports(self):
        pixmap = self.image()
        pixmap.setDevicePixelRatio(2)
        dialog = AnnotationDialog(pixmap)
        dialog.show()
        self.app.processEvents()
        canvas = dialog.canvas
        rect = canvas.image_rect()
        center = canvas.image_point(rect.center())
        self.assertAlmostEqual(center.x(), 100)
        self.assertAlmostEqual(center.y(), 60)
        self.assertIsNone(canvas.image_point(QPointF(0, 0)))
        start = (rect.topLeft() + QPointF(15, 15)).toPoint()
        end = (rect.center()).toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(canvas.marks), 1)
        dialog.copy_result()
        copied = self.app.clipboard().pixmap()
        self.assertEqual(copied.size(), pixmap.size())
        self.assertEqual(copied.devicePixelRatio(), 2)
        emitted = []
        dialog.pin_requested.connect(emitted.append)
        dialog.pin_result()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].toImage(), canvas.result().toImage())
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'edited.png')
            with patch('annotation_ui.QFileDialog.getSaveFileName', return_value=(path, '')):
                dialog.save_result()
            self.assertEqual(QImage(path).size(), pixmap.size())
        self.assertEqual(pixmap.toImage().pixelColor(0, 0), QColor('white'))
        self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
        dialog.close()

    def test_editor_integrates_with_pin_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(False, QSettings(str(Path(tmp)/'test.ini'), QSettings.IniFormat))
            pin = window.add_pin(self.image(), QPoint(30, 30))
            pin.edit_requested.emit(pin)
            self.assertEqual(len(window.editors), 1)
            editor = window.editors[0]
            editor.canvas.commit(Mark('rectangle', QPointF(10, 10), QPointF(50, 50)))
            editor.pin_result()
            self.assertEqual(len(window.pins), 2)
            self.assertNotEqual(window.pins[-1].pixmap.toImage(), pin.pixmap.toImage())
            window.cleanup()
            self.assertFalse(editor.isVisible())
            self.app.processEvents()
            window.close()
            self.app.processEvents()
