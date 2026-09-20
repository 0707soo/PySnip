"""Non-destructive annotation editor; exported images contain flattened edits."""
import math
from dataclasses import dataclass
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget)


@dataclass
class Mark:
    tool: str
    start: QPointF
    end: QPointF
    color: str = '#ef4444'
    width: int = 3
    text: str = ''
    font_size: int = 24
    block: int = 12


def render_marks(original, marks):
    image = original.copy()
    image.setDevicePixelRatio(1)
    for mark in marks:
        rect = QRectF(mark.start, mark.end).normalized()
        if mark.tool == 'mosaic':
            area = rect.toAlignedRect().intersected(image.rect())
            if area.isEmpty():
                continue
            patch = image.copy(area)
            patch = patch.scaled(max(1, area.width() // mark.block), max(1, area.height() // mark.block),
                                 Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            patch = patch.scaled(area.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(area.topLeft(), patch)
            painter.end()
            continue
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(mark.color), mark.width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if mark.tool == 'rectangle':
            painter.drawRect(rect)
        elif mark.tool == 'arrow':
            painter.drawLine(mark.start, mark.end)
            angle = math.atan2(mark.end.y() - mark.start.y(), mark.end.x() - mark.start.x())
            length = min(math.hypot(rect.width(), rect.height()) / 2, max(12, mark.width * 4))
            points = [mark.end]
            for offset in (-0.5, 0.5):
                points.append(mark.end - QPointF(length * math.cos(angle + offset), length * math.sin(angle + offset)))
            painter.setBrush(QColor(mark.color))
            painter.drawPolygon(QPolygonF(points))
        elif mark.tool == 'text':
            font = QFont('Malgun Gothic')
            font.setPixelSize(mark.font_size)
            painter.setFont(font)
            painter.drawText(QRectF(mark.start.x(), mark.start.y(), image.width() - mark.start.x(),
                                   image.height() - mark.start.y()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, mark.text)
        painter.end()
    return image


class AnnotationCanvas(QWidget):
    changed = Signal()

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.dpr = pixmap.devicePixelRatio()
        self.original = pixmap.toImage().copy()
        self.original.setDevicePixelRatio(1)
        self.marks = []
        self.redo_marks = []
        self.rendered = self.original.copy()
        self.tool = 'rectangle'
        self.color = '#ef4444'
        self.width_px = 3
        self.font_size = 24
        self.block = 12
        self.start_point = None
        self.end_point = None
        self.setMinimumSize(240, 160)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def image_rect(self):
        available = self.rect().adjusted(8, 8, -8, -8)
        size = self.original.size().scaled(available.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                      size.width(), size.height())

    def image_point(self, point, clamp=False):
        rect = self.image_rect()
        if not clamp and not rect.contains(point):
            return None
        x = (point.x() - rect.x()) * self.original.width() / rect.width()
        y = (point.y() - rect.y()) * self.original.height() / rect.height()
        return QPointF(min(self.original.width() - 1, max(0, x)), min(self.original.height() - 1, max(0, y)))

    def mark(self, start, end, text=''):
        return Mark(self.tool, start, end, self.color, self.width_px, text, self.font_size, self.block)

    def commit(self, mark):
        self.marks.append(mark)
        self.redo_marks.clear()
        self.rendered = render_marks(self.rendered, [mark])
        self.changed.emit()
        self.update()

    def cancel_stroke(self):
        self.start_point = self.end_point = None
        self.update()

    def undo(self):
        self.cancel_stroke()
        if self.marks:
            self.redo_marks.append(self.marks.pop())
            self.rendered = render_marks(self.original, self.marks)
            self.changed.emit()
            self.update()

    def redo(self):
        self.cancel_stroke()
        if self.redo_marks:
            mark = self.redo_marks.pop()
            self.marks.append(mark)
            self.rendered = render_marks(self.rendered, [mark])
            self.changed.emit()
            self.update()

    def result(self):
        pixmap = QPixmap.fromImage(self.rendered)
        pixmap.setDevicePixelRatio(self.dpr)
        return pixmap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#30343b'))
        rect = self.image_rect()
        painter.fillRect(rect, Qt.GlobalColor.white)
        painter.drawImage(rect, self.rendered)
        if self.start_point is not None and self.end_point is not None:
            # Preview in image coordinates without re-rendering the full-size bitmap.
            painter.save()
            painter.setClipRect(rect)
            painter.translate(rect.topLeft())
            painter.scale(rect.width() / self.original.width(), rect.height() / self.original.height())
            painter.setPen(QPen(QColor(self.color), self.width_px, Qt.PenStyle.DashLine))
            if self.tool == 'arrow':
                painter.drawLine(self.start_point, self.end_point)
            else:
                painter.drawRect(QRectF(self.start_point, self.end_point).normalized())
            painter.restore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.cancel_stroke()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.image_point(event.position())
        if point is None:
            return
        if self.tool == 'text':
            text, accepted = QInputDialog.getMultiLineText(self, '텍스트 추가', '이미지에 표시할 내용:')
            if accepted and text.strip():
                self.commit(self.mark(point, point, text))
            return
        self.start_point = self.end_point = point
        self.update()

    def mouseMoveEvent(self, event):
        if self.start_point is not None:
            self.end_point = self.image_point(event.position(), clamp=True)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.start_point is None:
            return
        end = self.image_point(event.position(), clamp=True)
        rect = QRectF(self.start_point, end).normalized()
        valid = (math.hypot(rect.width(), rect.height()) >= 2 if self.tool == 'arrow'
                 else rect.width() >= 2 and rect.height() >= 2)
        if valid:
            self.commit(self.mark(self.start_point, end))
        self.cancel_stroke()


class AnnotationDialog(QDialog):
    pin_requested = Signal(QPixmap)

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle('PySnip — 이미지 편집')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.tool = QComboBox()
        for label, value in [('사각형', 'rectangle'), ('화살표', 'arrow'), ('텍스트', 'text'), ('모자이크', 'mosaic')]:
            self.tool.addItem(label, value)
        toolbar.addWidget(self.tool)
        self.canvas = AnnotationCanvas(pixmap)
        self.tool.currentIndexChanged.connect(self.change_tool)
        color = QPushButton('색상')
        color.clicked.connect(self.choose_color)
        toolbar.addWidget(color)
        for label, low, high, default, attribute in [('선', 1, 30, 3, 'width_px'),
                ('글자', 8, 200, 24, 'font_size'), ('모자이크', 4, 100, 12, 'block')]:
            toolbar.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(default)
            spin.setSuffix(' px')
            spin.valueChanged.connect(lambda value, name=attribute: setattr(self.canvas, name, value))
            toolbar.addWidget(spin)
        layout.addLayout(toolbar)
        layout.addWidget(self.canvas, 1)
        self.notice = QLabel('드래그하여 그리기 · 텍스트는 클릭하여 입력 · 우클릭으로 그리기 취소')
        layout.addWidget(self.notice)
        actions = QHBoxLayout()
        self.undo_button = QPushButton('실행 취소 (Ctrl+Z)')
        self.redo_button = QPushButton('다시 실행 (Ctrl+Y)')
        self.undo_button.clicked.connect(self.canvas.undo)
        self.redo_button.clicked.connect(self.canvas.redo)
        actions.addWidget(self.undo_button)
        actions.addWidget(self.redo_button)
        for label, callback in [('복사', self.copy_result), ('저장', self.save_result),
                                ('결과 새로 고정', self.pin_result), ('닫기', self.close)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        for key, callback in [('Ctrl+Z', self.canvas.undo), ('Ctrl+Y', self.canvas.redo),
                              ('Ctrl+C', self.copy_result), ('Ctrl+S', self.save_result)]:
            QShortcut(QKeySequence(key), self, activated=callback)
        self.canvas.changed.connect(self.update_actions)
        self.update_actions()
        available = QApplication.primaryScreen().availableGeometry().size()
        self.setFixedSize(QSize(min(960, available.width() - 40), min(680, available.height() - 60)).expandedTo(self.minimumSizeHint()))

    def change_tool(self):
        self.canvas.cancel_stroke()
        self.canvas.tool = self.tool.currentData()

    def update_actions(self):
        self.undo_button.setEnabled(bool(self.canvas.marks))
        self.redo_button.setEnabled(bool(self.canvas.redo_marks))

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.canvas.color), self, '주석 색상')
        if color.isValid():
            self.canvas.color = color.name()

    def copy_result(self):
        QApplication.clipboard().setPixmap(self.canvas.result())
        self.notice.setText('편집 결과를 클립보드에 복사했습니다. 원본 이미지는 유지됩니다.')

    def save_result(self):
        filename, _ = QFileDialog.getSaveFileName(self, '편집 이미지 저장', 'annotated.png', 'PNG 이미지 (*.png)')
        if filename:
            if not filename.lower().endswith('.png'):
                filename += '.png'
            if not self.canvas.result().save(filename, 'PNG'):
                QMessageBox.warning(self, '저장 실패', '파일 경로와 쓰기 권한을 확인해 주세요.')
            else:
                self.notice.setText('편집 결과를 저장했습니다.')

    def pin_result(self):
        self.pin_requested.emit(self.canvas.result())
        self.notice.setText('편집 결과를 새 이미지로 고정했습니다. 원본 이미지는 유지됩니다.')
