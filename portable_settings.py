"""Store readable settings next to the executable, never its extraction folder."""
import json
from pathlib import Path
import sys
from PySide6.QtCore import QSettings
from hotkeys import DEFAULTS, validate_bindings


def settings_path():
    entry = Path(sys.executable) if getattr(sys, 'frozen', False) else Path(__file__)
    return entry.resolve().parent / 'PySnip.ini'


def open_settings(path=None, legacy=None):
    path = Path(path) if path is not None else settings_path()
    exists = path.exists()
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.setFallbacksEnabled(False)
    if not exists:
        old = legacy if legacy is not None else QSettings('PySnip', 'PySnip')
        bindings = dict(DEFAULTS)
        opacity, border = 100, 1
        try:
            saved = json.loads(old.value('hotkeys', '{}'))
            candidate = {name: saved.get(name, default) for name, default in DEFAULTS.items()}
            validate_bindings(candidate, check_reserved=False)
            bindings = candidate
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            saved = json.loads(old.value('appearance', '{}'))
            opacity = min(100, max(20, int(saved.get('opacity', 100))))
            border = min(20, max(0, int(saved.get('border', 1))))
        except (ValueError, TypeError, AttributeError):
            opacity, border = 100, 1
        for name, value in bindings.items():
            settings.setValue('Hotkeys/' + name, value)
        settings.setValue('Appearance/opacity', opacity)
        settings.setValue('Appearance/border', border)
        settings.setValue('OCR/language', 'ko-KR')
        settings.setValue('OCR/retry_scale', 2)
        settings.setValue('OCR/auto_copy', False)
        settings.setValue('Session/restore_pins', False)
        settings.setValue('History/limit', 0)
        settings.sync()
    return settings
