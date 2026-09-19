"""Headless check executed inside the frozen binary (no user settings modified)."""
import json
from pathlib import Path
import tempfile


def run(report_path):
    from PySide6.QtCore import QPoint, QSettings, QTimer
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
            report.write_text(json.dumps({'ok': True, 'ocr': results[0], 'checks': ['icon', 'portable INI path and persistence', 'global settings', 'three pins shutdown', 'bundled OCR helper']}, ensure_ascii=False, indent=2), encoding='utf-8')
        return 0
    except Exception as exc:
        report.write_text(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), encoding='utf-8')
        return 1
