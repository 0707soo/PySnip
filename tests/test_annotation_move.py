import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QPoint, QPointF, Qt, QSettings
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from annotation_ui import AnnotationCanvas, AnnotationDialog, Mark, mark_bounds, render_marks
from annotation_controls import ACTIVE_OPTIONS
from main import MainWindow


class AnnotationMoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        image = QPixmap(400, 240)
        image.fill('white')
        image.setDevicePixelRatio(2)
        self.canvas = AnnotationCanvas(image, inline=True)
        self.canvas.resize(200, 120)
        self.canvas.show()
        self.canvas.tool = 'select'

    def tearDown(self):
        self.canvas.close()
        self.app.processEvents()

    def drag(self, start, end):
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.canvas, end)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end)

    def test_all_movable_types_translate_and_undo_redo_at_scaled_size(self):
        examples = [
            (Mark('rectangle', QPointF(40,40), QPointF(140,100)), QPoint(30,30)),
            (Mark('ellipse', QPointF(40,40), QPointF(140,100)), QPoint(40,35)),
            (Mark('arrow', QPointF(40,60), QPointF(140,60)), QPoint(40,30)),
            (Mark('text', QPointF(40,40), QPointF(40,40), text='Text'), QPoint(25,25))]
        for mark, start in examples:
            with self.subTest(tool=mark.tool):
                self.canvas.marks = []
                self.canvas.undo_states = []
                self.canvas.redo_marks = []
                self.canvas.rendered = self.canvas.original.copy()
                self.canvas.commit(deepcopy(mark))
                before = self.canvas.rendered.copy()
                self.drag(start, start + QPoint(20,10))
                moved = self.canvas.marks[0]
                self.assertEqual(moved.start, mark.start + QPointF(40,20))
                self.assertEqual(moved.end, mark.end + QPointF(40,20))
                after = self.canvas.rendered.copy()
                self.assertNotEqual(before, after)
                self.canvas.undo()
                self.assertEqual(self.canvas.rendered, before)
                self.canvas.redo()
                self.assertEqual(self.canvas.rendered, after)
                self.assertEqual(self.canvas.result().devicePixelRatio(), 2)
                self.assertEqual(self.canvas.result().size(), self.canvas.original.size())

    def test_moving_rebuilds_original_without_ghost_and_keeps_layer_order(self):
        first = Mark('rectangle', QPointF(30,30), QPointF(90,90))
        second = Mark('rectangle', QPointF(30,30), QPointF(90,90), color='#0000ff')
        self.canvas.commit(first)
        self.canvas.commit(second)
        self.drag(QPoint(25,25), QPoint(75,25))
        self.assertEqual(self.canvas.marks[0], first)
        self.assertEqual(self.canvas.marks[1].start, QPointF(130,30))
        self.assertEqual(self.canvas.rendered.pixelColor(30,50).name(), '#ef4444')
        expected = render_marks(self.canvas.original, self.canvas.marks)
        self.assertEqual(self.canvas.result().toImage(), expected)

    def test_cancel_drag_noop_and_bounds(self):
        self.canvas.commit(Mark('rectangle', QPointF(40,40), QPointF(100,100)))
        before = self.canvas.rendered.copy()
        history = len(self.canvas.undo_states)
        self.drag(QPoint(30,30), QPoint(30,30))
        self.assertEqual(len(self.canvas.undo_states), history)
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(30,30))
        QTest.mouseMove(self.canvas, QPoint(60,40))
        QTest.mousePress(self.canvas, Qt.MouseButton.RightButton, pos=QPoint(60,40))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(60,40))
        self.assertEqual(self.canvas.rendered, before)
        self.assertEqual(len(self.canvas.undo_states), history)
        self.drag(QPoint(30,30), QPoint(199,119))
        bounds = mark_bounds(self.canvas.marks[0])
        self.assertLessEqual(bounds.right(), self.canvas.original.width())
        self.assertLessEqual(bounds.bottom(), self.canvas.original.height())

    def test_control_drag_draws_over_existing_shape(self):
        self.canvas.tool = 'rectangle'
        self.canvas.commit(Mark('rectangle', QPointF(20,20), QPointF(200,150)))
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(30,30))
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(60,60))
        self.assertEqual(len(self.canvas.marks), 2)
        self.assertEqual(self.canvas.marks[1].start, QPointF(60,60))

    def test_selection_excludes_flat_pixels_and_pen_marks(self):
        self.canvas.commit(Mark('pen', QPointF(20,20), QPointF(80,20), points=[QPointF(20,20),QPointF(80,20)]))
        self.assertIsNone(self.canvas.hit_test(QPointF(40,20)))
        self.assertIsNone(self.canvas.hit_test(QPointF(300,200)))

    def test_contextual_controls_compact_and_window_fixed(self):
        dialog = AnnotationDialog(QPixmap.fromImage(self.canvas.original))
        dialog.show()
        size = dialog.size()
        for tool, active in ACTIVE_OPTIONS.items():
            dialog.tool.setCurrentIndex(dialog.tool.findData(tool))
            self.app.processEvents()
            for name, (label, spin) in dialog.option_widgets.items():
                self.assertEqual(not label.isHidden(), name in active)
                self.assertEqual(not spin.isHidden(), name in active)
                if name in active:
                    self.assertLessEqual(spin.x() - (label.x() + label.width()), 6)
            self.assertEqual(dialog.size(), size)
            self.assertEqual(dialog.color_button.isHidden(), tool in ('mosaic','select'))
        dialog.close()
        self.app.processEvents()

    def test_direct_drawing_move_updates_pin_and_hides_unused_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(False, QSettings(str(Path(tmp)/'test.ini'),QSettings.IniFormat))
            pin = window.add_pin(QPixmap.fromImage(self.canvas.original),QPoint(20,20))
            pin.toggle_drawing()
            panel = pin.draw_panel
            canvas = pin.draw_canvas
            canvas.commit(Mark('rectangle',QPointF(40,40),QPointF(90,90)))
            panel.select_tool('select')
            self.assertTrue(panel.color_button.isHidden())
            self.assertTrue(all(group.isHidden() for group in panel.options.groups.values()))
            QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=QPoint(60,60))
            QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=QPoint(100,80))
            self.assertEqual(pin.pixmap.toImage(), canvas.rendered)
            self.assertEqual(canvas.marks[0].start,QPointF(80,60))
            panel.select_tool('mosaic')
            self.assertFalse(panel.options.groups['block'].isHidden())
            self.assertTrue(panel.marker_opacity.isHidden())
            window.cleanup()
            window.close()
            self.app.processEvents()
