"""Non-destructive annotation editor; exported images contain flattened edits."""
import math
from copy import deepcopy
from dataclasses import dataclass, field
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainterPath, QPainterPathStroker, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut
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
    points: list = field(default_factory=list)
    opacity: int = 40


TOOLS = [('펜', 'pen'), ('형광펜', 'marker'), ('사각형', 'rectangle'),
         ('타원', 'ellipse'), ('화살표', 'arrow'), ('텍스트', 'text'), ('모자이크', 'mosaic'), ('선택·이동', 'select')]

MOVABLE = {'rectangle', 'ellipse', 'arrow', 'text'}


def arrow_head(mark):
    angle = math.atan2(mark.end.y() - mark.start.y(), mark.end.x() - mark.start.x())
    length = min(math.hypot(mark.end.x() - mark.start.x(), mark.end.y() - mark.start.y()) / 2,
                 max(12, mark.width * 4))
    return QPolygonF([mark.end] + [mark.end - QPointF(length * math.cos(angle + offset),
                        length * math.sin(angle + offset)) for offset in (-0.5, 0.5)])


def text_bounds(mark):
    font = QFont('Malgun Gothic')
    font.setPixelSize(mark.font_size)
    bounds = QFontMetricsF(font).boundingRect(QRectF(0, 0, 100000, 100000),
                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, mark.text)
    return QRectF(mark.start.x(), mark.start.y(), max(1, bounds.width()), max(1, bounds.height()))


def mark_path(mark):
    path = QPainterPath()
    rect = QRectF(mark.start, mark.end).normalized()
    if mark.tool == 'rectangle':
        path.addRect(rect)
    elif mark.tool == 'ellipse':
        path.addEllipse(rect)
    elif mark.tool == 'arrow':
        path.moveTo(mark.start)
        path.lineTo(mark.end)
        path.addPolygon(arrow_head(mark))
    elif mark.tool == 'text':
        path.addRect(text_bounds(mark))
    return path


def mark_bounds(mark):
    bounds = mark_path(mark).boundingRect()
    pad = 0 if mark.tool == 'text' else mark.width / 2
    return bounds.adjusted(-pad, -pad, pad, pad)


def draw_marker(painter, mark, bounds):
    points = mark.points or [mark.start]
    area = QPolygonF(points).boundingRect().adjusted(-mark.width / 2 - 2, -mark.width / 2 - 2,
                                                   mark.width / 2 + 2, mark.width / 2 + 2)
    area = area.toAlignedRect().intersected(bounds)
    if area.isEmpty():
        return
    # Paint one opaque mask per stroke so crossing the same stroke doesn't make seams darker.
    layer = QImage(area.size(), QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(Qt.GlobalColor.transparent)
    stroke = QPainter(layer)
    stroke.setRenderHint(QPainter.RenderHint.Antialiasing)
    stroke.translate(-area.topLeft())
    stroke.setPen(QPen(QColor(mark.color), mark.width, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if len(points) == 1 or all(point == points[0] for point in points):
        stroke.drawPoint(points[0])
    else:
        stroke.drawPolyline(QPolygonF(points))
    stroke.end()
    painter.save()
    painter.setOpacity(min(100, max(1, mark.opacity)) / 100)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    painter.drawImage(area.topLeft(), layer)
    painter.restore()


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
        if mark.tool == 'marker':
            draw_marker(painter, mark, image.rect())
        elif mark.tool == 'pen':
            if len(mark.points) == 1:
                painter.drawPoint(mark.points[0])
            elif mark.points:
                painter.drawPolyline(QPolygonF(mark.points))
        elif mark.tool == 'rectangle':
            painter.drawRect(rect)
        elif mark.tool == 'ellipse':
            painter.drawEllipse(rect)
        elif mark.tool == 'arrow':
            painter.drawLine(mark.start, mark.end)
            painter.setBrush(QColor(mark.color))
            painter.drawPolygon(arrow_head(mark))
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

    def __init__(self, pixmap, parent=None, inline=False):
        super().__init__(parent)
        self.inline = inline
        self.stroke_points = []
        self.dpr = pixmap.devicePixelRatio()
        self.original = pixmap.toImage().copy()
        self.original.setDevicePixelRatio(1)
        self.marks = []
        self.redo_marks = []
        self.undo_states = []
        self.selected_index = None
        self.move_before = None
        self.move_origin = None
        self.rendered = self.original.copy()
        self.tool = 'rectangle'
        self.color = '#ef4444'
        self.width_px = 3
        self.marker_width = 20
        self.marker_color = '#facc15'
        self.marker_opacity = 40
        self.font_size = 24
        self.block = 12
        self.start_point = None
        self.end_point = None
        self.setMinimumSize(0, 0) if inline else self.setMinimumSize(240, 160)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def image_rect(self):
        if self.inline:
            return QRectF(self.rect())
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

    def active_color(self):
        return self.marker_color if self.tool == 'marker' else self.color

    def set_active_color(self, color):
        if self.tool == 'marker':
            self.marker_color = color
        else:
            self.color = color

    def mark(self, start, end, text=''):
        width = self.marker_width if self.tool == 'marker' else self.width_px
        return Mark(self.tool, start, end, self.active_color(), width, text, self.font_size, self.block, opacity=self.marker_opacity)

    def commit(self, mark):
        self.undo_states.append(deepcopy(self.marks))
        self.marks.append(mark)
        self.selected_index = len(self.marks) - 1 if mark.tool in MOVABLE else None
        self.redo_marks.clear()
        self.rendered = render_marks(self.rendered, [mark])
        self.changed.emit()
        self.update()

    def cancel_stroke(self):
        if self.move_before is not None:
            self.marks = self.move_before
            self.move_before = self.move_origin = None
            self.rendered = render_marks(self.original, self.marks)
        self.start_point = self.end_point = None
        self.stroke_points = []
        self.update()

    def undo(self):
        self.cancel_stroke()
        if self.undo_states:
            self.redo_marks.append(deepcopy(self.marks))
            self.marks = self.undo_states.pop()
            self.selected_index = None
            self.rendered = render_marks(self.original, self.marks)
            self.changed.emit()
            self.update()

    def redo(self):
        self.cancel_stroke()
        if self.redo_marks:
            self.undo_states.append(deepcopy(self.marks))
            self.marks = self.redo_marks.pop()
            self.selected_index = None
            self.rendered = render_marks(self.original, self.marks)
            self.changed.emit()
            self.update()

    def hit_test(self, point):
        if self.tool not in MOVABLE and self.tool != 'select':
            return None
        tolerance = 5 * self.original.width() / max(1, self.image_rect().width())
        for index in range(len(self.marks) - 1, -1, -1):
            mark = self.marks[index]
            if mark.tool not in MOVABLE:
                continue
            path = mark_path(mark)
            stroke = QPainterPathStroker()
            stroke.setWidth(mark.width + tolerance * 2)
            interior = (self.tool == 'select' or index == self.selected_index or mark.tool == 'text')
            if stroke.createStroke(path).contains(point) or (interior and path.contains(point)):
                return index
        return None

    def move_selection(self, point):
        if self.move_before is None:
            return
        before = self.move_before[self.selected_index]
        bounds = mark_bounds(before)
        delta = point - self.move_origin
        def clamp(value, low, high):
            return min(max(value, low), high) if low <= high else 0
        dx = clamp(delta.x(), min(0, -bounds.left()), max(0, self.original.width() - bounds.right()))
        dy = clamp(delta.y(), min(0, -bounds.top()), max(0, self.original.height() - bounds.bottom()))
        moved = deepcopy(before)
        moved.start += QPointF(dx, dy)
        moved.end += QPointF(dx, dy)
        self.marks[self.selected_index] = moved
        self.rendered = render_marks(self.original, self.marks)
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
        if self.selected_index is not None:
            bounds = mark_bounds(self.marks[self.selected_index])
            sx, sy = rect.width() / self.original.width(), rect.height() / self.original.height()
            selected = QRectF(rect.x() + bounds.x() * sx, rect.y() + bounds.y() * sy,
                              bounds.width() * sx, bounds.height() * sy)
            painter.save()
            painter.setClipRect(rect)
            painter.setPen(QPen(QColor('#38bdf8'), 1, Qt.PenStyle.DashLine))
            painter.drawRect(selected.adjusted(-3, -3, 3, 3))
            painter.restore()
        if self.start_point is not None and self.end_point is not None:
            # Preview in image coordinates without re-rendering the full-size bitmap.
            painter.save()
            painter.setClipRect(rect)
            painter.translate(rect.topLeft())
            painter.scale(rect.width() / self.original.width(), rect.height() / self.original.height())
            painter.setPen(QPen(QColor(self.color), self.width_px, Qt.PenStyle.DashLine))
            if self.tool == 'marker':
                mark = self.mark(self.start_point, self.end_point)
                mark.points = list(self.stroke_points)
                draw_marker(painter, mark, self.original.rect())
            elif self.tool == 'pen':
                painter.setPen(QPen(QColor(self.color), self.width_px, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                if len(self.stroke_points) == 1:
                    painter.drawPoint(self.stroke_points[0])
                else:
                    painter.drawPolyline(QPolygonF(self.stroke_points))
            elif self.tool == 'arrow':
                painter.drawLine(self.start_point, self.end_point)
            elif self.tool == 'ellipse':
                painter.drawEllipse(QRectF(self.start_point, self.end_point).normalized())
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
        hit = None if event.modifiers() & Qt.KeyboardModifier.ControlModifier else self.hit_test(point)
        if hit is not None:
            self.selected_index = hit
            self.move_origin = point
            self.move_before = deepcopy(self.marks)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            self.update()
            return
        self.selected_index = None
        if self.tool == 'select':
            self.update()
            return
        if self.tool == 'text':
            text, accepted = QInputDialog.getMultiLineText(self, '텍스트 추가', '이미지에 표시할 내용:')
            if accepted and text.strip():
                self.commit(self.mark(point, point, text))
            return
        self.start_point = self.end_point = point
        self.stroke_points = [point]
        self.update()

    def mouseMoveEvent(self, event):
        point = self.image_point(event.position(), clamp=True)
        if self.move_before is not None:
            self.move_selection(point)
            return
        self.setCursor(Qt.CursorShape.SizeAllCursor if self.hit_test(point) is not None
                       else Qt.CursorShape.CrossCursor)
        if self.start_point is not None:
            self.end_point = self.image_point(event.position(), clamp=True)
            if self.tool in ('pen', 'marker'):
                self.stroke_points.append(self.end_point)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.move_before is not None:
            self.move_selection(self.image_point(event.position(), clamp=True))
            before = self.move_before
            self.move_before = self.move_origin = None
            if self.marks != before:
                self.undo_states.append(before)
                self.redo_marks.clear()
                self.changed.emit()
            self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton or self.start_point is None:
            return
        end = self.image_point(event.position(), clamp=True)
        if self.tool in ('pen', 'marker'):
            self.stroke_points.append(end)
            mark = self.mark(self.start_point, end)
            mark.points = list(self.stroke_points)
            self.commit(mark)
            self.cancel_stroke()
            return
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
        for label, value in TOOLS:
            self.tool.addItem(label, value)
        toolbar.addWidget(self.tool)
        self.canvas = AnnotationCanvas(pixmap)
        self.canvas.tool = self.tool.currentData()
        self.tool.currentIndexChanged.connect(self.change_tool)
        self.tool.setFixedWidth(120)
        self.color_button = QPushButton('색상')
        self.color_button.setFixedWidth(100)
        self.color_button.clicked.connect(self.choose_color)
        toolbar.addWidget(self.color_button)
        from annotation_controls import CanvasOptions
        self.options = CanvasOptions(self.canvas)
        self.option_widgets = self.options.widgets
        toolbar.addWidget(self.options)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        layout.addWidget(self.canvas, 1)
        self.notice = QLabel('선택·이동: 도형·텍스트 드래그 · Ctrl+드래그: 겹쳐 그리기 · 우클릭: 작업 취소')
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
        self.update_options()
        available = QApplication.primaryScreen().availableGeometry().size()
        self.setFixedSize(QSize(min(960, available.width() - 40), min(680, available.height() - 60)).expandedTo(self.minimumSizeHint()))

    def change_tool(self):
        self.canvas.cancel_stroke()
        self.canvas.selected_index = None
        self.canvas.update()
        self.canvas.tool = self.tool.currentData()
        self.update_options()

    def update_options(self):
        self.options.update_tool()
        self.color_button.setVisible(self.canvas.tool not in ('mosaic', 'select'))

    def update_actions(self):
        self.undo_button.setEnabled(bool(self.canvas.undo_states))
        self.redo_button.setEnabled(bool(self.canvas.redo_marks))

    def choose_color(self):
        from color_palette import PaletteDialog
        dialog = PaletteDialog(self.canvas.active_color(), getattr(self.parent(), 'palette_store', None), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.canvas.set_active_color(dialog.color)
        dialog.deleteLater()

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
