import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget, QSlider, QSpinBox,
    QGroupBox, QButtonGroup, QRadioButton,
)

DEFAULTS = {'capture': 'F1', 'clipboard': 'F3', 'toggle': 'F2'}
LABELS = {'capture': '영역 캡처', 'clipboard': '클립보드 이미지·텍스트 고정', 'toggle': '고정 이미지 숨김·복원'}
KEYS = {f'F{i}': 0x6F + i for i in range(1, 25) if i != 12}
KEYS.update({chr(i): i for i in range(ord('A'), ord('Z') + 1)})
KEYS.update({str(i): ord(str(i)) for i in range(10)})
KEYS.update({f'Num{i}': 0x60 + i for i in range(10)})
SELECTABLE_KEYS = ([f'F{i}' for i in range(1, 12)]
                   + list('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
                   + list('1234567890'))
MODIFIERS = {'Ctrl': 2, 'Alt': 1, 'Shift': 4, 'Win': 8}


def parse_hotkey(text):
    parts = text.split('+')
    if not parts or parts[-1] not in KEYS:
        raise ValueError('지원하는 기능키, 영문자 또는 숫자를 선택하세요.')
    mods = parts[:-1]
    if len(set(mods)) != len(mods) or any(m not in MODIFIERS for m in mods):
        raise ValueError('올바른 보조키 조합을 선택하세요.')
    if not mods and not parts[-1].startswith('F'):
        raise ValueError('문자·숫자 키에는 Ctrl, Alt, Shift 중 하나를 추가하세요.')
    return sum(MODIFIERS[m] for m in mods), KEYS[parts[-1]]


def validate_bindings(bindings, check_reserved=True):
    specs = [parse_hotkey(bindings[name]) for name in bindings]
    if check_reserved:
        for name, (modifiers, key) in zip(bindings, specs):
            reason = None
            if modifiers & MODIFIERS['Win']:
                reason = 'Win 키 조합은 Windows 예약 단축키이므로 사용할 수 없습니다.'
            elif modifiers == MODIFIERS['Alt'] and key == KEYS['F4']:
                reason = 'Alt+F4는 창 닫기 단축키이므로 사용할 수 없습니다.'
            elif modifiers == MODIFIERS['Ctrl'] and key in (KEYS['C'], KEYS['S'], KEYS['T'], KEYS['E'], KEYS['L'], KEYS['Z'], KEYS['Y']):
                reason = 'Ctrl+C/S/T/E/L/Z/Y는 앱의 복사·저장·OCR·편집·잠금·실행 취소 기능에서 사용하는 단축키입니다.'
            if reason:
                raise ValueError(f'{LABELS[name]}: {reason}')
    if len(set(specs)) != len(specs):
        raise ValueError('여러 기능에 같은 단축키를 지정할 수 없습니다.')


class WindowsHotkeys(QAbstractNativeEventFilter):
    """Register new combinations before releasing old ones, preserving them on failure."""
    def __init__(self, callbacks, api=None):
        super().__init__()
        self.callbacks = callbacks
        self.api = api if api is not None else (ctypes.windll.user32 if sys.platform == 'win32' else None)
        self.active = {}

    def apply(self, bindings):
        validate_bindings(bindings)
        if self.api is None:
            raise ValueError('전역 단축키는 Windows에서 사용할 수 있습니다.')
        wanted = {parse_hotkey(text): name for name, text in bindings.items()}
        by_spec = {spec: identifier for identifier, (spec, _) in self.active.items()}
        pending = {}
        try:
            for spec, name in wanted.items():
                if spec in by_spec:
                    continue
                identifier = next(i for i in range(1, 0xC000) if i not in self.active and i not in pending)
                if not self.api.RegisterHotKey(None, identifier, spec[0] | 0x4000, spec[1]):
                    raise ValueError(f'{LABELS[name]}: {bindings[name]} 등록 실패. 다른 프로그램 또는 Windows에서 사용 중일 수 있습니다.')
                pending[identifier] = (spec, name)
        except Exception:
            for identifier in pending:
                self.api.UnregisterHotKey(None, identifier)
            raise
        for identifier, (spec, _) in list(self.active.items()):
            if spec not in wanted:
                self.api.UnregisterHotKey(None, identifier)
                del self.active[identifier]
            else:
                self.active[identifier] = (spec, wanted[spec])
        self.active.update(pending)

    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32':
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.active:
                spec, name = self.active[msg.wParam]
                # Ignore messages queued for an earlier registration of this ID.
                if (int(msg.lParam) & 0xFFFF, (int(msg.lParam) >> 16) & 0xFFFF) == spec:
                    QTimer.singleShot(0, self.callbacks[name])
                return True, 0
        return False, 0

    def unregister(self):
        for identifier in list(self.active):
            self.api.UnregisterHotKey(None, identifier)
        self.active.clear()


class HotkeyEditor(QWidget):
    changed = Signal()
    def __init__(self, text):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.modifiers = {}
        for name in ('Ctrl', 'Alt', 'Shift'):
            checkbox = QCheckBox(name)
            self.modifiers[name] = checkbox
            layout.addWidget(checkbox)
        self.key = QComboBox()
        for key in SELECTABLE_KEYS:
            self.key.addItem(key, key)
        layout.addWidget(self.key)
        self.num = QCheckBox('Num')
        self.num.setToolTip('체크: 숫자패드 / 해제: 상단 숫자열')
        layout.addWidget(self.num)
        self.key.currentIndexChanged.connect(self.update_num_visibility)
        self.set_value(text)
        self.key.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self.num.toggled.connect(lambda _checked: self.changed.emit())
        for checkbox in self.modifiers.values():
            checkbox.toggled.connect(lambda _checked: self.changed.emit())

    def update_num_visibility(self):
        numeric = str(self.key.currentData()).isdigit()
        self.num.setVisible(numeric)
        if not numeric:
            self.num.setChecked(False)

    def set_value(self, text):
        parts = text.split('+')
        # Show unsupported legacy bindings explicitly until the user replaces them.
        legacy_win = 'Win' in parts[:-1]
        for name, checkbox in self.modifiers.items():
            checkbox.setChecked(not legacy_win and name in parts[:-1])
        key = text if legacy_win else parts[-1]
        if legacy_win and self.key.findData(key) < 0:
            self.key.addItem(f'{text} (기존 설정 · 변경 필요)', key)
        is_num = key.startswith('Num') and key[3:].isdigit()
        if is_num:
            key = key[3:]
        index = self.key.findData(key)
        if index < 0 and key in KEYS:
            # Keep old F13–F24 assignments until the user explicitly changes them.
            self.key.addItem(f'{key} (기존 설정)', key)
            index = self.key.count() - 1
        self.key.setCurrentIndex(max(0, index))
        self.update_num_visibility()
        self.num.setChecked(is_num and key.isdigit())

    def value(self):
        key = self.key.currentData()
        if key.isdigit() and self.num.isChecked():
            key = 'Num' + key
        return '+'.join([name for name, box in self.modifiers.items() if box.isChecked()] + [key])


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('설정')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('단축키와 이미지 표시 설정을 저장하면 전체에 적용됩니다.'))
        form = QFormLayout()
        self.editors = {}
        for name, label in LABELS.items():
            editor = HotkeyEditor(parent.bindings[name])
            self.editors[name] = editor
            form.addRow(label, editor)
        layout.addLayout(form)
        hint = QLabel('문자·숫자는 보조키가 필요합니다. F12는 Windows 예약 키로 제외됩니다.')
        hint.setText('문자·숫자는 보조키가 필요합니다. 숫자패드는 Num Lock을 켜고 사용하세요.\nF12는 Windows 예약 키로 제외됩니다.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        appearance = QFormLayout()
        opacity_row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(20, 100)
        self.opacity = QSpinBox()
        self.opacity.setRange(20, 100)
        self.opacity.setSuffix(' %')
        self.slider.valueChanged.connect(self.opacity.setValue)
        self.opacity.valueChanged.connect(self.slider.setValue)
        self.opacity.setValue(parent.opacity_percent)
        opacity_row.addWidget(self.slider)
        opacity_row.addWidget(self.opacity)
        appearance.addRow('불투명도', opacity_row)
        self.border = QSpinBox()
        self.border.setRange(0, 20)
        self.border.setSuffix(' px')
        self.border.setValue(parent.border_width)
        appearance.addRow('테두리 두께', self.border)
        layout.addLayout(appearance)
        layout.addWidget(QLabel('불투명도 100%: 완전히 선명 / 테두리 0px: 선 없음\n현재·새 이미지에 공통 적용되며 다음 실행에도 유지됩니다.'))
        ocr_group = QGroupBox('OCR')
        ocr_form = QFormLayout(ocr_group)
        self.ocr_language = QComboBox()
        self.ocr_language.addItem('한국어 (한글·영문 혼합)', 'ko-KR')
        self.ocr_language.addItem('영어', 'en-US')
        self.ocr_language.setCurrentIndex(max(0, self.ocr_language.findData(parent.ocr_language)))
        ocr_form.addRow('기본 언어', self.ocr_language)
        scale_row = QHBoxLayout()
        self.ocr_scale = QButtonGroup(self)
        for value, label in [(1, '하지 않음'), (2, '2배'), (4, '4배')]:
            option = QRadioButton(label)
            self.ocr_scale.addButton(option, value)
            option.setChecked(value == parent.ocr_scale)
            scale_row.addWidget(option)
        ocr_form.addRow('확대 후 인식 시도', scale_row)
        ocr_form.addRow(QLabel('원본 인식 실패 시 선택한 배율로 한 번 재시도합니다.'))
        self.ocr_auto_copy = QCheckBox('인식 결과 자동 복사')
        self.ocr_auto_copy.setChecked(parent.ocr_auto_copy)
        ocr_form.addRow(self.ocr_auto_copy)
        ocr_setup = QPushButton('OCR 언어 활성화 / 설치 상태')
        ocr_setup.clicked.connect(lambda: parent.open_ocr_settings(self))
        ocr_form.addRow(ocr_setup)
        layout.addWidget(ocr_group)
        self.restore_pins = QCheckBox('다음 실행 시 고정 이미지 복원')
        self.restore_pins.setChecked(parent.restore_pins)
        self.restore_pins.setToolTip('종료 시 이미지와 위치·확대율을 앱 폴더에 저장합니다.')
        layout.addWidget(self.restore_pins)
        history_form = QFormLayout()
        self.history_limit = QSpinBox()
        self.history_limit.setRange(0, 999999)
        self.history_limit.setSpecialValueText('0 (무제한)')
        self.history_limit.setValue(parent.history_limit)
        history_form.addRow('닫은 이미지 보관 개수', self.history_limit)
        history_form.addRow(QLabel('최근에 닫은 이미지부터 복원합니다. 보관 기록은 종료 시 비워집니다.'))
        layout.addLayout(history_form)
        reset = QPushButton('전체 기본값 복원')
        reset.clicked.connect(self.reset_defaults)
        layout.addWidget(reset)
        self.validation = QLabel()
        self.validation.setWordWrap(True)
        self.validation.setMinimumHeight(40)
        self.validation.setStyleSheet('color: #c2410c;')
        layout.addWidget(self.validation)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('저장')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for editor in self.editors.values():
            editor.changed.connect(self.validate_selection)
        self.validate_selection()
        self.setFixedSize(QSize(600, 500).expandedTo(self.sizeHint()))

    def validate_selection(self):
        try:
            validate_bindings({name: editor.value() for name, editor in self.editors.items()})
        except ValueError as exc:
            self.validation.setText(str(exc))
            self.save_button.setEnabled(False)
        else:
            self.validation.clear()
            self.save_button.setEnabled(True)

    def reset_defaults(self):
        for name, editor in self.editors.items():
            editor.set_value(DEFAULTS[name])
        self.opacity.setValue(100)
        self.border.setValue(1)
        self.ocr_language.setCurrentIndex(0)
        self.ocr_scale.button(2).setChecked(True)
        self.ocr_auto_copy.setChecked(False)
        self.restore_pins.setChecked(False)
        self.history_limit.setValue(0)

    def save(self):
        try:
            self.parent().apply_settings({name: editor.value() for name, editor in self.editors.items()}, self.opacity.value(), self.border.value(), self.ocr_language.currentData(), self.ocr_scale.checkedId(), self.ocr_auto_copy.isChecked(), self.restore_pins.isChecked(), self.history_limit.value())
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '설정', str(exc))
            return
        self.accept()
