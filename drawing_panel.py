"""Compact controls for drawing directly on an existing pin."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QSpinBox, QLabel, QComboBox
from color_palette import PaletteDialog
from annotation_ui import TOOLS


class DrawingPanel(QDialog):
    def __init__(self, pin):
        super().__init__(pin, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.pin = pin
        self.canvas = pin.draw_canvas
        self.setWindowTitle('이미지 위에 그리기')
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        tool = QComboBox()
        for label, value in TOOLS:
            tool.addItem(label, value)
        tool.currentIndexChanged.connect(lambda: self.select_tool(tool.currentData()))
        row.addWidget(tool)
        color = QPushButton('색상 · 즐겨찾기')
        color.clicked.connect(self.choose_color)
        row.addWidget(color)
        self.size_label = QLabel('선 두께')
        row.addWidget(self.size_label)
        self.size_spin = width = QSpinBox()
        width.setRange(1, 30)
        width.setValue(self.canvas.width_px)
        width.setSuffix(' px')
        width.valueChanged.connect(self.set_size)
        row.addWidget(width)
        layout.addLayout(row)
        marker_row = QHBoxLayout()
        marker_row.addWidget(QLabel('형광펜 진하기'))
        self.marker_opacity = QSpinBox()
        self.marker_opacity.setRange(10, 80)
        self.marker_opacity.setValue(self.canvas.marker_opacity)
        self.marker_opacity.setSuffix(' %')
        self.marker_opacity.valueChanged.connect(lambda value: setattr(self.canvas, 'marker_opacity', value))
        self.marker_opacity.setEnabled(False)
        marker_row.addWidget(self.marker_opacity)
        layout.addLayout(marker_row)
        row = QHBoxLayout()
        self.undo = QPushButton('실행 취소')
        self.redo = QPushButton('다시 실행')
        self.undo.clicked.connect(self.canvas.undo)
        self.redo.clicked.connect(self.canvas.redo)
        row.addWidget(self.undo)
        row.addWidget(self.redo)
        for label, callback in [('복사', pin.copy_image), ('저장', pin.save_image), ('완료 (Esc)', pin.stop_drawing)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(QLabel('이미지 위에 드래그 · 우클릭: 현재 선 취소 · Ctrl+Z/Y: 실행 취소/다시 실행'))
        for key, callback in [('Ctrl+Z', self.canvas.undo), ('Ctrl+Y', self.canvas.redo),
                              ('Ctrl+C', pin.copy_image), ('Ctrl+S', pin.save_image)]:
            QShortcut(QKeySequence(key), self, activated=callback)
        self.canvas.changed.connect(self.refresh)
        self.finished.connect(pin.stop_drawing)
        self.refresh()
        self.setFixedSize(self.sizeHint())

    def select_tool(self, tool):
        self.canvas.cancel_stroke()
        self.canvas.tool = tool
        attribute, label, low, high = self.size_option()
        self.size_label.setText(label)
        self.size_spin.blockSignals(True)
        self.size_spin.setRange(low, high)
        self.size_spin.setValue(getattr(self.canvas, attribute))
        self.size_spin.blockSignals(False)
        self.marker_opacity.setEnabled(tool == 'marker')

    def size_option(self):
        return {'marker': ('marker_width', '형광펜 두께', 4, 100),
                'text': ('font_size', '글자 크기', 8, 200),
                'mosaic': ('block', '모자이크 크기', 4, 100)}.get(self.canvas.tool, ('width_px', '선 두께', 1, 30))

    def set_size(self, value):
        setattr(self.canvas, self.size_option()[0], value)

    def choose_color(self):
        dialog = PaletteDialog(self.canvas.active_color(), self.pin.palette_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.canvas.set_active_color(dialog.color)
        dialog.deleteLater()

    def refresh(self):
        self.undo.setEnabled(bool(self.canvas.marks))
        self.redo.setEnabled(bool(self.canvas.redo_marks))

    def show_near_pin(self):
        bounds = self.pin.screen().availableGeometry()
        x = min(max(self.pin.x(), bounds.left()), bounds.right() - self.width() + 1)
        y = self.pin.y() - self.height() - 8
        if y < bounds.top():
            y = self.pin.y() + self.pin.height() + 8
        y = min(max(y, bounds.top()), bounds.bottom() - self.height() + 1)
        self.move(QPoint(x, y))
        self.show()
