import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QMimeData
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from annotation_ui import AnnotationCanvas, AnnotationDialog, Mark, render_marks
from main import MainWindow
from text_pin import normalize_card, render_card
from pin_session import load_session


class SnipasteFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name)/'test.ini')
        self.window = MainWindow(False, QSettings(self.path, QSettings.IniFormat))

    def tearDown(self):
        self.window.cleanup()
        self.window.close()
        self.app.processEvents()
        self.directory.cleanup()

    def white(self):
        image = QImage(200, 120, QImage.Format_ARGB32_Premultiplied)
        image.fill('white')
        return image

    def test_text_card_plain_text_wrap_and_high_resolution(self):
        value = {'text': '한국어 메모\nEnglish <b>literal</b> & <img src="https://invalid.example/x">'}
        card = normalize_card(value)
        image = render_card(card)
        self.assertEqual(card['text'], value['text'])
        self.assertEqual(image.devicePixelRatio(), 2)
        self.assertEqual(image.width(), 960)
        self.assertEqual(image.toImage().pixelColor(0, 0), QColor('#fffde7'))
        self.assertGreater(render_card({'text':'same\n' * 5}).height(), render_card({'text':'same'}).height())
        self.assertEqual(render_card({'text':'W' * 300, 'width':200}).width(), 400)
        for invalid in [{'text':''}, {'text':' '}, {'text':'x'*20001}, {'text':'x','width':50},
                        {'text':'x','foreground':'not-color'}, {'text':'x\n' * 4000}]:
            with self.assertRaises(ValueError):
                render_card(invalid)

    def test_clipboard_text_pin_edit_and_source_copy(self):
        self.app.clipboard().setText('원문 text')
        self.window.pin_clipboard()
        pin = self.window.pins[0]
        self.assertEqual(pin.text_card['text'], '원문 text')
        self.assertEqual(self.app.clipboard().text(), '원문 text')
        self.window.open_text_editor(pin)
        dialog = self.window.editors[0]
        dialog.text.setPlainText('수정한 text')
        dialog.font_size.setValue(24)
        dialog.save()
        self.assertEqual(pin.text_card['text'], '수정한 text')
        self.assertEqual(pin.text_card['font_size'], 24)
        pin.copy_source_text()
        self.assertEqual(self.app.clipboard().text(), '수정한 text')
        pin.copy_image()
        self.assertFalse(self.app.clipboard().pixmap().isNull())
        self.app.processEvents()

    def test_clipboard_image_has_priority_and_invalid_text_adds_nothing(self):
        data = QMimeData()
        data.setText('image takes priority')
        data.setImageData(self.white())
        self.app.clipboard().setMimeData(data)
        self.window.pin_clipboard()
        self.assertIsNone(self.window.pins[0].text_card)
        self.assertEqual(self.window.pins[0].pixmap.size(), self.white().size())
        self.app.clipboard().setText('x'*20001)
        with patch('main.QMessageBox.warning') as warning:
            self.window.pin_clipboard()
            warning.assert_called_once()
        self.assertEqual(len(self.window.pins), 1)

    def test_text_edit_cancel_and_annotation_replacement_confirmation(self):
        self.app.clipboard().setText('original')
        self.window.pin_clipboard()
        pin = self.window.pins[0]
        self.window.open_text_editor(pin)
        dialog = self.window.editors[0]
        dialog.text.setPlainText('cancelled')
        dialog.reject()
        self.assertEqual(pin.text_card['text'], 'original')
        pin.toggle_drawing()
        pin.draw_canvas.commit(Mark('rectangle', QPointF(5, 5), QPointF(30, 30)))
        before = pin.pixmap.toImage()
        self.window.open_text_editor(pin)
        editor = self.window.editors[0]
        editor.text.setPlainText('new')
        with patch('main.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            editor.save()
        self.assertEqual(pin.pixmap.toImage(), before)
        self.assertEqual(pin.text_card['text'], 'original')
        with patch('main.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            editor.save()
        self.assertEqual(pin.text_card['text'], 'new')
        self.assertIsNone(pin.draw_canvas)
        self.app.processEvents()

    def test_text_source_survives_history_session_and_old_session(self):
        self.app.clipboard().setText('persist 한글')
        self.window.pin_clipboard()
        self.window.pins[0].close_without_confirmation()
        self.window.restore_closed_pin()
        self.assertEqual(self.window.pins[0].text_card['text'], 'persist 한글')
        self.window.restore_pins = True
        self.window.cleanup()
        records = load_session(self.window.session_path)
        self.assertEqual(records[0][6]['text'], 'persist 한글')
        restored = MainWindow(False, QSettings(self.path, QSettings.IniFormat))
        restored.restore_pins = True
        restored.restore_session()
        self.assertEqual(restored.pins[0].text_card['text'], 'persist 한글')
        restored.pins[0].copy_source_text()
        self.assertEqual(self.app.clipboard().text(), 'persist 한글')
        restored.cleanup()
        restored.close()
        self.app.processEvents()
        old = json.loads(self.window.session_path.read_text(encoding='utf-8'))
        del old['pins'][0]['text_card']
        self.window.session_path.write_text(json.dumps(old), encoding='utf-8')
        self.assertIsNone(load_session(self.window.session_path)[0][6])

    def test_closing_pin_also_closes_text_editor(self):
        self.app.clipboard().setText('close')
        self.window.pin_clipboard()
        pin = self.window.pins[0]
        self.window.open_text_editor(pin)
        pin.close_without_confirmation()
        self.assertEqual(self.window.editors, [])
        self.app.processEvents()

    def test_marker_preserves_dark_text_no_seams_and_undo(self):
        image = self.white()
        image.setPixelColor(80, 40, QColor('black'))
        points = [QPointF(20,40), QPointF(140,40), QPointF(20,40)]
        mark = Mark('marker', points[0], points[-1], color='#ffff00', width=20, points=points, opacity=40)
        result = render_marks(image, [mark])
        self.assertEqual(result.pixelColor(80,40), QColor('black'))
        self.assertEqual(result.pixelColor(60,40).red(), 255)
        self.assertTrue(145 <= result.pixelColor(60,40).blue() <= 160)
        single = render_marks(image, [Mark('marker', points[0], points[1], color='#ffff00', width=20, points=points[:2], opacity=40)])
        self.assertEqual(result.pixelColor(60,40), single.pixelColor(60,40))
        self.assertEqual(result.pixelColor(60,70), QColor('white'))
        canvas = AnnotationCanvas(QPixmap.fromImage(image))
        canvas.commit(mark)
        canvas.undo()
        self.assertEqual(canvas.rendered, canvas.original)
        canvas.redo()
        self.assertEqual(canvas.rendered, render_marks(canvas.original, [mark]))
        canvas.close()

    def test_ellipse_reverse_drag_and_tool_controls(self):
        image = self.white()
        mark = Mark('ellipse', QPointF(100,60), QPointF(20,20), width=3)
        result = render_marks(image, [mark])
        self.assertNotEqual(result.pixelColor(60,20), QColor('white'))
        self.assertEqual(result.pixelColor(60,40), QColor('white'))
        self.assertEqual(result.pixelColor(20,20), QColor('white'))
        dialog = AnnotationDialog(QPixmap.fromImage(image), self.window)
        dialog.tool.setCurrentIndex(dialog.tool.findData('marker'))
        self.assertEqual(dialog.canvas.tool, 'marker')
        self.assertTrue(dialog.option_widgets['marker_width'][1].isEnabled())
        self.assertFalse(dialog.option_widgets['width_px'][1].isEnabled())
        dialog.canvas.set_active_color('#112233')
        dialog.tool.setCurrentIndex(dialog.tool.findData('pen'))
        self.assertEqual(dialog.canvas.color, '#ef4444')
        dialog.tool.setCurrentIndex(dialog.tool.findData('marker'))
        self.assertEqual(dialog.canvas.active_color(), '#112233')
        pin = self.window.add_pin(QPixmap.fromImage(image), QPoint(20,20))
        pin.toggle_drawing()
        panel = pin.draw_panel
        panel.select_tool('marker')
        panel.size_spin.setValue(35)
        panel.marker_opacity.setValue(60)
        self.assertEqual(pin.draw_canvas.marker_width, 35)
        self.assertEqual(pin.draw_canvas.marker_opacity, 60)
        panel.select_tool('text')
        panel.size_spin.setValue(32)
        self.assertEqual(pin.draw_canvas.font_size, 32)
        self.assertFalse(panel.marker_opacity.isEnabled())
        dialog.close()
        self.app.processEvents()
