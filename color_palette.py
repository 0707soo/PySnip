"""Shared portable favorite colors and a fixed-size palette picker."""
import json
import re
from PySide6.QtCore import QObject, Signal, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget,
    QPushButton, QLabel, QLineEdit, QColorDialog, QScrollArea, QDialogButtonBox)

PRESETS = ['#ef4444','#f97316','#f59e0b','#eab308','#84cc16','#22c55e','#10b981','#14b8a6',
           '#06b6d4','#0ea5e9','#3b82f6','#6366f1','#8b5cf6','#a855f7','#d946ef','#ec4899',
           '#ffffff','#e5e7eb','#9ca3af','#6b7280','#374151','#111827','#000000','#92400e']


def normalize_color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError('색상은 #RRGGBB 형식으로 입력하세요.')
    return value.lower()


class PaletteStore(QObject):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.favorites = []
        try:
            saved = json.loads(settings.value('Drawing/favorite_colors', '[]'))
            if isinstance(saved, list):
                for value in saved:
                    try:
                        color = normalize_color(value)
                        if color not in self.favorites:
                            self.favorites.append(color)
                    except ValueError:
                        pass
        except (ValueError, TypeError):
            pass

    def toggle(self, color):
        color = normalize_color(color)
        updated = list(self.favorites)
        if color in updated:
            updated.remove(color)
        else:
            updated.append(color)
        self.settings.setValue('Drawing/favorite_colors', json.dumps(updated))
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            raise OSError('즐겨찾기를 저장하지 못했습니다. INI 폴더의 쓰기 권한을 확인하세요.')
        self.favorites = updated
        self.changed.emit()


class PaletteDialog(QDialog):
    def __init__(self, color, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle('색상 팔레트')
        self.store = store
        self.color = normalize_color(color)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('기본 팔레트'))
        grid = QGridLayout()
        for i, value in enumerate(PRESETS):
            grid.addWidget(self.swatch(value), i // 8, i % 8)
        layout.addLayout(grid)
        row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(36, 28)
        row.addWidget(self.preview)
        self.hex = QLineEdit(self.color)
        self.hex.setMaxLength(7)
        self.hex.textChanged.connect(self.validate_input)
        row.addWidget(self.hex)
        custom = QPushButton('사용자 색상…')
        custom.clicked.connect(self.custom_color)
        row.addWidget(custom)
        layout.addLayout(row)
        self.favorite = QPushButton()
        self.favorite.clicked.connect(self.toggle_favorite)
        layout.addWidget(self.favorite)
        layout.addWidget(QLabel('즐겨찾기 · 클릭하여 선택'))
        area = QScrollArea()
        area.setWidgetResizable(True)
        self.favorite_widget = QWidget()
        self.favorite_grid = QGridLayout(self.favorite_widget)
        area.setWidget(self.favorite_widget)
        layout.addWidget(area)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText('적용')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if store is not None:
            store.changed.connect(self.refresh_favorites)
        self.refresh_favorites()
        self.validate_input()
        self.setFixedSize(420, 420)

    def swatch(self, color):
        button = QPushButton()
        button.setFixedSize(34, 26)
        button.setToolTip(color.upper())
        button.setAccessibleName(color.upper())
        button.setStyleSheet(f'background-color: {color}; border: 1px solid #888;')
        button.clicked.connect(lambda: self.hex.setText(color))
        return button

    def validate_input(self):
        try:
            self.color = normalize_color(self.hex.text())
        except ValueError as exc:
            self.error.setText(str(exc))
            self.ok.setEnabled(False)
            self.favorite.setEnabled(False)
            return
        self.error.clear()
        self.ok.setEnabled(True)
        self.favorite.setEnabled(self.store is not None)
        self.preview.setStyleSheet(f'background-color: {self.color}; border: 1px solid #888;')
        self.favorite.setText('★ 즐겨찾기에서 제거' if self.store and self.color in self.store.favorites else '☆ 즐겨찾기에 추가')

    def refresh_favorites(self):
        while self.favorite_grid.count():
            item = self.favorite_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, color in enumerate(self.store.favorites if self.store else []):
            self.favorite_grid.addWidget(self.swatch(color), i // 8, i % 8)
        self.validate_input()

    def toggle_favorite(self):
        try:
            self.store.toggle(self.color)
        except OSError as exc:
            self.error.setText(str(exc))

    def custom_color(self):
        color = QColorDialog.getColor(QColor(self.color), self, '사용자 색상')
        if color.isValid():
            self.hex.setText(color.name())
