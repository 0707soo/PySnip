import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QSettings
from portable_settings import open_settings, settings_path


class PortableSettingsTests(unittest.TestCase):
    def test_migrate_once_and_move_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = QSettings(str(root / 'legacy.ini'), QSettings.Format.IniFormat)
            legacy.setValue('hotkeys', json.dumps({'capture': 'Ctrl+F1', 'clipboard': 'F3'}))
            legacy.setValue('appearance', json.dumps({'opacity': 70, 'border': 3}))
            path = root / 'PySnip.ini'
            settings = open_settings(path, legacy)
            self.assertTrue(path.is_file())
            self.assertEqual(settings.value('Hotkeys/capture'), 'Ctrl+F1')
            settings.setValue('Appearance/opacity', 85)
            settings.sync()
            reopened = open_settings(path, legacy)
            self.assertEqual(int(reopened.value('Appearance/opacity')), 85)
            moved = root / 'moved'
            moved.mkdir()
            shutil.copy2(path, moved / 'PySnip.ini')
            portable = open_settings(moved / 'PySnip.ini', legacy)
            self.assertEqual(int(portable.value('Appearance/opacity')), 85)
            self.assertEqual(int(portable.value('Appearance/border')), 3)
            text = path.read_text(encoding='utf-8')
            self.assertIn('[Appearance]', text)
            self.assertIn('[Hotkeys]', text)

    def test_frozen_path_is_executable_directory(self):
        with patch('portable_settings.sys.frozen', True, create=True), patch('portable_settings.sys.executable', r'C:\Portable\PySnip.exe'):
            self.assertEqual(settings_path(), Path(r'C:\Portable\PySnip.ini'))

    def test_invalid_legacy_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = QSettings(str(Path(directory) / 'legacy.ini'), QSettings.Format.IniFormat)
            legacy.setValue('appearance', 'invalid')
            legacy.setValue('hotkeys', 'invalid')
            settings = open_settings(Path(directory) / 'PySnip.ini', legacy)
            self.assertEqual(int(settings.value('Appearance/opacity')), 100)
            self.assertEqual(int(settings.value('Appearance/border')), 1)
