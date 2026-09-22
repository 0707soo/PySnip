"""Headless check executed inside the frozen binary (no user settings modified)."""
import json
from pathlib import Path
import tempfile


def run(report_path):
    from PySide6.QtCore import QPoint, QPointF, QSettings, QTimer
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from main import MainWindow
    from ocr_ui import OcrJob
    from portable_settings import settings_path, open_settings
    import sys
    report = Path(report_path)
    try:
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        if getattr(sys, 'frozen', False):
            assert settings_path() == Path(sys.executable).resolve().parent / 'PySnip.ini'
        with tempfile.TemporaryDirectory(prefix='pysnip-check-') as folder:
            settings = open_settings(Path(folder) / 'PySnip.ini', QSettings(str(Path(folder) / 'empty.ini'), QSettings.Format.IniFormat))
            window = MainWindow(False, settings)
            assert not window.windowIcon().pixmap(32, 32).isNull(), 'Missing bundled SVG icon'
            pixmap = QPixmap(80, 40)
            pixmap.fill()
            for index in range(3):
                window.add_pin(pixmap, QPoint(index * 100, 0))
            window.apply_settings(window.bindings, 60, 2)
            reread = QSettings(str(Path(folder) / 'PySnip.ini'), QSettings.Format.IniFormat)
            assert int(reread.value('Appearance/opacity')) == 60
            assert int(reread.value('Appearance/border')) == 2
            assert all(pin.opacity_percent == 60 and pin.border_width == 2 for pin in window.pins)
            from annotation_ui import Mark
            from text_pin import normalize_card, render_card
            from pin_session import save_session, load_session
            from version import __version__
            card = normalize_card({'text': 'PySnip release check / 한국어'})
            text_pin = window.add_pin(render_card(card), QPoint(10, 10))
            text_pin.text_card = card
            text_pin.toggle_drawing()
            text_pin.draw_canvas.commit(Mark('marker', QPointF(10, 20), QPointF(100, 20),
                color='#ffff00', width=15, points=[QPointF(10, 20), QPointF(100, 20)]))
            assert text_pin.draw_canvas.marks, 'Direct drawing failed'
            text_pin.stop_drawing()
            text_pin.toggle_thumbnail()
            window.palette_store.toggle('#123456')
            assert '#123456' in window.palette_store.favorites
            save_session(window.session_path, window.pins)
            loaded = load_session(window.session_path)
            assert loaded[-1][5] and loaded[-1][6]['text'] == card['text']
            window.open_editor(text_pin)
            window.open_text_editor(text_pin)
            results = []
            job = OcrJob('Status')
            job.completed.connect(lambda result: (results.append(result), window.quit_app()))
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(lambda: app.exit(42))
            timeout.start(30000)
            QTimer.singleShot(0, job.start)
            code = app.exec()
            timeout.stop()
            job.stop()
            assert code == 0 and results and results[0].get('ok'), f'OCR bridge failed: {results}'
            assert not window.pins, 'Pin windows remained after shutdown'
            assert not window.editors, 'Editors remained after shutdown'
            report.write_text(json.dumps({'ok': True, 'version': __version__, 'ocr': results[0], 'checks': ['icon', 'portable INI path and persistence', 'global settings', 'multiple pins and editors shutdown', 'bundled OCR helper', 'text card and thumbnail persistence', 'direct marker drawing', 'favorite colors']}, ensure_ascii=False, indent=2), encoding='utf-8')
        return 0
    except Exception as exc:
        report.write_text(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), encoding='utf-8')
        return 1
