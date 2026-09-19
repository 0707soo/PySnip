import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QSettings
from PySide6.QtCore import QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from hotkeys import DEFAULTS, SettingsDialog, HotkeyEditor, WindowsHotkeys, parse_hotkey, validate_bindings
from main import MainWindow


class FakeAPI:
    def __init__(self):
        self.registered = {}
        self.blocked = set()

    def RegisterHotKey(self, hwnd, identifier, mods, key):
        spec = (mods & ~0x4000, key)
        if spec in self.blocked or spec in self.registered.values():
            return False
        self.registered[identifier] = spec
        return True

    def UnregisterHotKey(self, hwnd, identifier):
        self.registered.pop(identifier, None)
        return True


class HotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_validation(self):
        self.assertEqual(parse_hotkey('Ctrl+Shift+A'), (6, 65))
        for key in ['A', 'F12', 'Ctrl+Ctrl+A', 'Ctrl+?', '']:
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_hotkey(key)
        with self.assertRaises(ValueError):
            validate_bindings({'capture': 'Ctrl+Alt+A', 'clipboard': 'Alt+Ctrl+A'})

    def test_number_row_and_numpad_are_distinct(self):
        self.assertEqual(parse_hotkey('Ctrl+1'), (2, 0x31))
        self.assertEqual(parse_hotkey('Ctrl+Num1'), (2, 0x61))
        validate_bindings({'capture': 'Ctrl+1', 'clipboard': 'Ctrl+Num1'})
        api = FakeAPI()
        manager = WindowsHotkeys({}, api)
        manager.apply({'capture': 'Ctrl+1', 'clipboard': 'Ctrl+Num1'})
        self.assertEqual(set(api.registered.values()), {(2, 0x31), (2, 0x61)})
        manager.unregister()
        editor = HotkeyEditor('Ctrl+Num0')
        self.assertEqual(editor.value(), 'Ctrl+Num0')
        self.assertEqual(editor.key.currentText(), '0')
        self.assertTrue(editor.num.isChecked())
        self.assertFalse(editor.num.isHidden())
        self.assertEqual(editor.key.findData('Num0'), -1)
        editor.set_value('Ctrl+0')
        self.assertEqual(editor.value(), 'Ctrl+0')
        self.assertFalse(editor.num.isChecked())
        editor.num.setChecked(True)
        self.assertEqual(editor.value(), 'Ctrl+Num0')
        editor.key.setCurrentIndex(editor.key.findData('A'))
        self.assertTrue(editor.num.isHidden())
        self.assertFalse(editor.num.isChecked())
        self.assertEqual(editor.value(), 'Ctrl+A')
        editor.key.setCurrentIndex(editor.key.findData('1'))
        self.assertFalse(editor.num.isHidden())
        self.assertEqual(editor.value(), 'Ctrl+1')
        self.assertEqual(editor.key.findData('F13'), -1)
        self.assertEqual(editor.key.findData('F24'), -1)
        editor.set_value('F24')
        self.assertEqual(editor.value(), 'F24')
        self.assertIn('기존 설정', editor.key.currentText())
        editor.deleteLater()

    def test_registration_failure_preserves_previous_and_releases_pending(self):
        api = FakeAPI()
        manager = WindowsHotkeys({}, api)
        manager.apply(DEFAULTS)
        before = dict(api.registered)
        api.blocked.add(parse_hotkey('Ctrl+B'))
        with self.assertRaises(ValueError):
            manager.apply({'capture': 'Ctrl+A', 'clipboard': 'Ctrl+B'})
        self.assertEqual(api.registered, before)
        self.assertEqual(len(manager.active), len(DEFAULTS))
        manager.unregister()
        self.assertEqual(api.registered, {})

    def test_swap_and_replace(self):
        api = FakeAPI()
        manager = WindowsHotkeys({}, api)
        manager.apply(DEFAULTS)
        manager.apply({'capture': 'F3', 'clipboard': 'F1'})
        assignments = {spec: name for spec, name in manager.active.values()}
        self.assertEqual(assignments[parse_hotkey('F3')], 'capture')
        manager.apply({'capture': 'Ctrl+Shift+A', 'clipboard': 'Alt+F8'})
        self.assertEqual(set(api.registered.values()), {parse_hotkey('Ctrl+Shift+A'), parse_hotkey('Alt+F8')})
        manager.unregister()

    def test_reserved_combinations_do_not_replace_registered_keys(self):
        api = FakeAPI()
        manager = WindowsHotkeys({}, api)
        manager.apply(DEFAULTS)
        before = dict(api.registered)
        for sequence in ['Win+D', 'Win+Ctrl+A', 'Alt+F4', 'Ctrl+C', 'Ctrl+S', 'Ctrl+T']:
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                manager.apply({'capture': sequence, 'clipboard': 'F3'})
            self.assertEqual(api.registered, before)
        manager.unregister()

    def test_reserved_selection_has_inline_message_and_disabled_save(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'test.ini'), QSettings.Format.IniFormat)
            settings.setValue('Hotkeys/capture', 'Win+D')
            window = MainWindow(False, settings)
            self.assertEqual(window.bindings['capture'], 'Win+D')
            dialog = SettingsDialog(window)
            self.assertNotIn('Win', dialog.editors['capture'].modifiers)
            self.assertEqual(dialog.editors['capture'].value(), 'Win+D')
            self.assertFalse(dialog.save_button.isEnabled())
            self.assertIn('Windows', dialog.validation.text())
            dialog.editors['capture'].set_value('Ctrl+Alt+D')
            self.assertTrue(dialog.save_button.isEnabled())
            self.assertEqual(dialog.validation.text(), '')
            dialog.save()
            self.assertEqual(window.bindings['capture'], 'Ctrl+Alt+D')
            window.cleanup()
            window.deleteLater()

    def test_dialog_save_reload_cancel_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'settings.ini')
            settings = QSettings(path, QSettings.Format.IniFormat)
            window = MainWindow(False, settings)
            dialog = SettingsDialog(window)
            dialog.editors['capture'].set_value('Ctrl+Shift+A')
            dialog.editors['clipboard'].set_value('Ctrl+Num1')
            dialog.ocr_language.setCurrentIndex(1)
            dialog.ocr_scale.button(4).setChecked(True)
            dialog.save()
            self.assertEqual(window.bindings['capture'], 'Ctrl+Shift+A')
            self.assertIn('Ctrl+Shift+A', window.action_buttons[0].text())
            restored = MainWindow(False, QSettings(path, QSettings.Format.IniFormat))
            self.assertEqual(restored.bindings, window.bindings)
            self.assertEqual(restored.bindings['clipboard'], 'Ctrl+Num1')
            self.assertEqual(restored.ocr_language, 'en-US')
            self.assertEqual(restored.ocr_scale, 4)
            cancelled = SettingsDialog(restored)
            cancelled.reset_defaults()
            cancelled.reject()
            self.assertEqual(restored.bindings['capture'], 'Ctrl+Shift+A')
            self.assertEqual(restored.ocr_scale, 4)
            reset = SettingsDialog(restored)
            reset.reset_defaults()
            reset.save()
            self.assertEqual(restored.bindings, DEFAULTS)
            self.assertEqual(restored.border_width, 1)
            self.assertEqual(restored.ocr_language, 'ko-KR')
            self.assertEqual(restored.ocr_scale, 2)
            window.cleanup()
            restored.cleanup()
            window.deleteLater()
            restored.deleteLater()

    def test_global_appearance_existing_new_reload_cancel_and_wheel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'settings.ini')
            window = MainWindow(False, QSettings(path, QSettings.Format.IniFormat))
            image = QPixmap(80, 40)
            image.fill()
            first = window.add_pin(image, QPoint())
            second = window.add_pin(image, QPoint(100, 0))
            dialog = SettingsDialog(window)
            dialog.opacity.setValue(65)
            dialog.border.setValue(4)
            self.assertEqual(first.opacity_percent, 100)
            dialog.save()
            third = window.add_pin(image, QPoint(200, 0))
            for pin in (first, second, third):
                self.assertEqual((pin.opacity_percent, pin.border_width), (65, 4))
                self.assertEqual(pin.size().toTuple(), (88, 48))
            cancelled = SettingsDialog(window)
            cancelled.reset_defaults()
            cancelled.reject()
            self.assertEqual((window.opacity_percent, window.border_width), (65, 4))
            first.opacity_requested.emit(70)
            self.assertTrue(all(pin.opacity_percent == 70 for pin in window.pins))
            restored = MainWindow(False, QSettings(path, QSettings.Format.IniFormat))
            self.assertEqual((restored.opacity_percent, restored.border_width), (70, 4))
            self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
            window.cleanup()
            restored.cleanup()
            window.deleteLater()
            restored.deleteLater()


if __name__ == '__main__':
    unittest.main()

