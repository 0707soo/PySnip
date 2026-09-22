"""Compact tool-specific label/input pairs shared by both drawing toolbars."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSpinBox, QSizePolicy


ACTIVE_OPTIONS = {
    'pen': ('width_px',), 'rectangle': ('width_px',), 'ellipse': ('width_px',),
    'arrow': ('width_px',), 'text': ('font_size',), 'mosaic': ('block',),
    'marker': ('marker_width', 'marker_opacity'), 'select': (),
}


class CanvasOptions(QWidget):
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.widgets = {}
        self.groups = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        for name, label, low, high, suffix in [
                ('width_px', '선 두께', 1, 30, ' px'),
                ('font_size', '글자 크기', 8, 200, ' px'),
                ('block', '모자이크 크기', 4, 100, ' px'),
                ('marker_width', '형광펜 두께', 4, 100, ' px'),
                ('marker_opacity', '진하기', 10, 80, ' %')]:
            group = QWidget()
            pair = QHBoxLayout(group)
            pair.setContentsMargins(0, 0, 0, 0)
            pair.setSpacing(4)
            label_widget = QLabel(label)
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(getattr(canvas, name))
            spin.setSuffix(suffix)
            spin.setFixedWidth(86)
            label_widget.setBuddy(spin)
            spin.valueChanged.connect(lambda value, attribute=name: setattr(canvas, attribute, value))
            pair.addWidget(label_widget)
            pair.addWidget(spin)
            layout.addWidget(group)
            self.groups[name] = group
            self.widgets[name] = (label_widget, spin)
        self.update_tool()

    def update_tool(self):
        active = ACTIVE_OPTIONS[self.canvas.tool]
        for name, group in self.groups.items():
            visible = name in active
            group.setVisible(visible)
            for widget in self.widgets[name]:
                widget.setVisible(visible)
