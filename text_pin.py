"""Plain clipboard text rendered as portable image cards with editable source."""
import math
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap, QTextDocument, QTextCursor, QTextCharFormat, QTextOption
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QSpinBox,
    QPushButton, QLabel, QDialogButtonBox)
from color_palette import normalize_color, PaletteDialog


def normalize_card(value):
    if not isinstance(value, dict):
        raise ValueError('텍스트 카드 정보가 올바르지 않습니다.')
    text = value.get('text', '')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('고정할 텍스트를 입력하세요.')
    if len(text) > 20000:
        raise ValueError('텍스트는 한 카드에 20,000자까지 입력할 수 있습니다. 나누어 고정해 주세요.')
    try:
        size, width = int(value.get('font_size', 18)), int(value.get('width', 480))
    except (ValueError, TypeError, OverflowError):
        raise ValueError('글자 크기와 카드 너비는 숫자여야 합니다.') from None
    if not 10 <= size <= 64 or not 200 <= width <= 1000:
        raise ValueError('글자 크기는 10~64px, 카드 너비는 200~1000px로 지정하세요.')
    return {'text': text, 'font_size': size, 'width': width,
            'foreground': normalize_color(value.get('foreground', '#172033')),
            'background': normalize_color(value.get('background', '#fffde7'))}


def render_card(value):
    card = normalize_card(value)
    document = QTextDocument()
    document.setDocumentMargin(0)
    font = QFont('Malgun Gothic')
    font.setPixelSize(card['font_size'])
    document.setDefaultFont(font)
    option = document.defaultTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    # Plain text must never be interpreted as HTML or cause remote resources to load.
    document.setPlainText(card['text'])
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.SelectionType.Document)
    formatting = QTextCharFormat()
    formatting.setForeground(QColor(card['foreground']))
    cursor.mergeCharFormat(formatting)
    document.setTextWidth(card['width'] - 32)
    height = max(64, math.ceil(document.size().height()) + 32)
    if height > 4096:
        raise ValueError('텍스트 카드가 너무 깁니다. 내용을 나누거나 카드 너비를 늘려 주세요.')
    image = QImage(card['width'] * 2, height * 2, QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull():
        raise ValueError('텍스트 이미지를 만들 메모리가 부족합니다.')
    image.setDevicePixelRatio(2)
    image.fill(QColor(card['background']))
    painter = QPainter(image)
    painter.translate(16, 16)
    document.drawContents(painter, QRectF(0, 0, card['width'] - 32, height - 32))
    painter.end()
    return QPixmap.fromImage(image)


class TextCardDialog(QDialog):
    def __init__(self, pin, apply_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle('텍스트 카드 편집')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.target_pin = pin
        self.apply_callback = apply_callback
        self.card = normalize_card(pin.text_card)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(self.card['text'])
        self.text.setPlaceholderText('고정할 텍스트')
        layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel('글자 크기'))
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 64)
        self.font_size.setSuffix(' px')
        self.font_size.setValue(self.card['font_size'])
        row.addWidget(self.font_size)
        row.addWidget(QLabel('카드 너비'))
        self.width_px = QSpinBox()
        self.width_px.setRange(200, 1000)
        self.width_px.setSuffix(' px')
        self.width_px.setValue(self.card['width'])
        row.addWidget(self.width_px)
        for label, field in [('글자 색상', 'foreground'), ('배경 색상', 'background')]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, name=field: self.choose_color(name))
            row.addWidget(button)
        layout.addLayout(row)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(200)
        self.preview.setStyleSheet('background: #30343b;')
        layout.addWidget(self.preview)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        layout.addWidget(QLabel('카드를 수정하면 직접 그린 주석은 초기화됩니다. 변경 전 확인합니다.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText('적용')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        for signal in (self.text.textChanged, self.font_size.valueChanged, self.width_px.valueChanged):
            signal.connect(lambda: self.timer.start(150))
        self.setFixedSize(640, 640)
        self.refresh()

    def values(self):
        return normalize_card({**self.card, 'text': self.text.toPlainText(),
                               'font_size': self.font_size.value(), 'width': self.width_px.value()})

    def refresh(self):
        try:
            image = render_card(self.values())
        except ValueError as exc:
            self.error.setText(str(exc))
            self.preview.clear()
            self.save_button.setEnabled(False)
            return
        self.error.clear()
        self.save_button.setEnabled(True)
        thumbnail = image.scaled(600, 190, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        thumbnail.setDevicePixelRatio(1)
        self.preview.setPixmap(thumbnail)

    def choose_color(self, field):
        dialog = PaletteDialog(self.card[field], self.target_pin.palette_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.card[field] = dialog.color
            self.refresh()
        dialog.deleteLater()

    def save(self):
        self.timer.stop()
        try:
            card = self.values()
            if self.apply_callback(card, render_card(card)):
                self.accept()
        except ValueError as exc:
            self.error.setText(str(exc))
