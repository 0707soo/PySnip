"""Compact controls for drawing directly on an existing pin."""
from PySide6.QtCore import QPoint, QSize, Qt
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
        self.tool = tool = QComboBox()
        for label, value in TOOLS:
            tool.addItem(label, value)
        tool.currentIndexChanged.connect(lambda: self.select_tool(tool.currentData()))
        row.addWidget(tool)
        self.color_button = color = QPushButton('색상 · 즐겨찾기')
        color.clicked.connect(self.choose_color)
        row.addWidget(color)
        tool.setFixedWidth(110)
        color.setFixedWidth(120)
        from annotation_controls import CanvasOptions
        self.options = CanvasOptions(self.canvas)
        row.addWidget(self.options)
        row.addStretch(1)
        layout.addLayout(row)
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
        layout.addWidget(QLabel('선택·이동: 도형·텍스트 드래그 · Ctrl+드래그: 겹쳐 그리기 · 우클릭: 작업 취소'))
        for key, callback in [('Ctrl+Z', self.canvas.undo), ('Ctrl+Y', self.canvas.redo),
                              ('Ctrl+C', pin.copy_image), ('Ctrl+S', pin.save_image)]:
            QShortcut(QKeySequence(key), self, activated=callback)
        self.canvas.changed.connect(self.refresh)
        self.finished.connect(pin.stop_drawing)
        self.refresh()
        self.setFixedSize(QSize(700, 132).expandedTo(self.sizeHint()))

    def select_tool(self, tool):
        self.canvas.cancel_stroke()
        self.canvas.selected_index = None
        self.canvas.update()
        self.canvas.tool = tool
        self.tool.blockSignals(True)
        self.tool.setCurrentIndex(self.tool.findData(tool))
        self.tool.blockSignals(False)
        self.options.update_tool()
        self.color_button.setVisible(tool not in ('mosaic', 'select'))

    @property
    def size_spin(self):
        attribute = {'marker': 'marker_width', 'text': 'font_size', 'mosaic': 'block'}.get(self.canvas.tool, 'width_px')
        return self.options.widgets[attribute][1]

    @property
    def marker_opacity(self):
        return self.options.widgets['marker_opacity'][1]

    def choose_color(self):
        dialog = PaletteDialog(self.canvas.active_color(), self.pin.palette_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.canvas.set_active_color(dialog.color)
        dialog.deleteLater()

    def refresh(self):
        self.undo.setEnabled(bool(self.canvas.undo_states))
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
