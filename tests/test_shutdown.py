"""Run real Qt event loops in child processes to detect lingering applications."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ShutdownTests(unittest.TestCase):
    def test_exit_button_with_multiple_pins_and_tray(self):
        script = '''
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QPushButton
from main import MainWindow

class Tray:
    visible = True
    def isVisible(self): return self.visible
    def hide(self): self.visible = False

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
window = MainWindow(enable_integrations=False)
window.tray = Tray()
window.show()
image = QPixmap(40, 40)
image.fill()
for i in range(3):
    window.add_pin(image, QPoint(i * 50, 0))
button = next(b for b in window.findChildren(QPushButton) if b.text() == '종료')
QTimer.singleShot(0, button.click)
# A quit rejected by closeEvent must fail, rather than hang the test runner.
QTimer.singleShot(1000, lambda: app.exit(42))
result = app.exec()
assert result == 0, f'Exit was rejected: {result}'
assert not window.pins, 'Pin windows were not cleaned up'
assert not window.tray.isVisible(), 'Tray icon still visible'
'''
        result = subprocess.run(
            [sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
