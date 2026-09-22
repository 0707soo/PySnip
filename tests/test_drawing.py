import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import MainWindow
from color_palette import PaletteDialog, PaletteStore
from annotation_ui import Mark
from pin_session import load_session


class DrawingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = QSettings(str(Path(self.tmp.name)/'test.ini'), QSettings.IniFormat)
        self.window = MainWindow(False, self.settings)
        image = QPixmap(400, 200)
        image.fill('white')
        image.setDevicePixelRatio(2)
        self.pin = self.window.add_pin(image, QPoint(200, 200))

    def tearDown(self):
        self.window.cleanup()
        self.window.close()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_inline_pen_coordinate_mapping_and_escape_undo(self):
        self.pin.toggle_drawing()
        canvas = self.pin.draw_canvas
        self.assertEqual(canvas.parent(), self.pin)
        self.assertEqual(canvas.geometry(), self.pin.rect().adjusted(1, 1, -1, -1))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 15))
        QTest.mouseMove(canvas, QPoint(60, 15))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 15))
        self.assertEqual(len(canvas.marks), 1)
        self.assertEqual(canvas.marks[0].tool, 'pen')
        self.assertEqual(canvas.marks[0].points[0], QPointF(20, 30))
        self.assertEqual(self.pin.pixmap.toImage().pixelColor(70, 30).name(), '#ef4444')
        self.assertEqual(canvas.original.pixelColor(70, 30), QColor('white'))
        edited = self.pin.pixmap.toImage()
        self.pin.undo_drawing()
        self.assertEqual(self.pin.pixmap.toImage().pixelColor(70, 30), QColor('white'))
        self.pin.redo_drawing()
        self.assertEqual(self.pin.pixmap.toImage(), edited)
        self.pin.activateWindow()
        canvas.setFocus()
        self.app.processEvents()
        with patch('main.QMessageBox.exec') as close_prompt:
            QTest.keyClick(canvas, Qt.Key.Key_Escape)
            close_prompt.assert_not_called()
        self.assertFalse(self.pin.drawing)
        self.assertTrue(self.pin.isVisible())
        self.assertFalse(self.pin.draw_panel.isVisible())
        self.pin.toggle_drawing()
        self.assertEqual(len(canvas.marks), 1)

    def test_lock_thumbnail_hide_and_shutdown_persist_output(self):
        self.pin.toggle_thumbnail()
        self.pin.toggle_drawing()
        self.assertFalse(self.pin.thumbnail)
        self.pin.draw_canvas.commit(Mark('pen', QPointF(10, 10), QPointF(50, 10),
                                         points=[QPointF(10, 10), QPointF(50, 10)]))
        expected = self.pin.pixmap.toImage()
        self.pin.toggle_lock()
        self.assertFalse(self.pin.drawing)
        self.pin.toggle_drawing()
        self.assertFalse(self.pin.drawing)
        self.pin.toggle_lock()
        self.pin.toggle_drawing()
        self.window.toggle_pins()
        self.assertFalse(self.pin.drawing)
        self.assertFalse(self.pin.draw_panel.isVisible())
        self.window.restore_pins = True
        self.window.cleanup()
        self.assertEqual(load_session(self.window.session_path)[0][0].toImage(), expected)

    def test_palette_favorites_shared_persisted_normalized_and_removed(self):
        store = self.window.palette_store
        first = PaletteDialog('#ef4444', store)
        second = PaletteDialog('#ef4444', store)
        first.hex.setText('#12ABef')
        first.toggle_favorite()
        self.assertEqual(store.favorites, ['#12abef'])
        self.assertEqual(second.favorite_grid.count(), 1)
        reloaded = PaletteStore(QSettings(self.settings.fileName(), QSettings.IniFormat))
        self.assertEqual(reloaded.favorites, store.favorites)
        first.hex.setText('#nope')
        self.assertFalse(first.ok.isEnabled())
        self.assertFalse(first.favorite.isEnabled())
        first.hex.setText('#12abef')
        first.toggle_favorite()
        self.assertEqual(store.favorites, [])
        self.assertEqual(second.favorite_grid.count(), 0)
        first.close()
        second.close()

    def test_palette_ignores_invalid_ini_entries_and_reports_write_error(self):
        self.settings.setValue('Drawing/favorite_colors', json.dumps(['#FF0000', 'oops', '#ff0000', 42]))
        store = PaletteStore(self.settings)
        self.assertEqual(store.favorites, ['#ff0000'])
        palette = PaletteDialog('#ffffff', store)
        with patch.object(store, 'toggle', side_effect=OSError('쓰기 실패')):
            palette.toggle_favorite()
        self.assertIn('쓰기 실패', palette.error.text())
        palette.close()
