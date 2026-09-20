"""Pixel-accurate capture loupe, sampled from the untouched screenshot."""
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap


def magnified_patch(screenshot, point, radius=10, zoom=7):
    ratio = screenshot.devicePixelRatio()
    x = min(screenshot.width() - 1, max(0, round(point.x() * ratio)))
    y = min(screenshot.height() - 1, max(0, round(point.y() * ratio)))
    size = radius * 2 + 1
    source = QRect(x - radius, y - radius, size, size)
    clipped = source.intersected(screenshot.rect())
    patch = QPixmap(size, size)
    patch.fill(QColor('#20242b'))
    sample = screenshot.copy(clipped)
    sample.setDevicePixelRatio(1)
    painter = QPainter(patch)
    painter.drawPixmap(clipped.topLeft() - source.topLeft(), sample)
    painter.end()
    return patch.scaled(size * zoom, size * zoom, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation)


def draw_magnifier(painter, screenshot, point, bounds, selection):
    patch = magnified_patch(screenshot, point)
    width, height = patch.width(), patch.height() + 26
    x, y = point.x() + 24, point.y() + 24
    if x + width > bounds.right():
        x = point.x() - width - 24
    if y + height > bounds.bottom():
        y = point.y() - height - 24
    x, y = max(bounds.left(), x), max(bounds.top(), y)
    painter.save()
    painter.fillRect(QRect(x, y, width, height), QColor('#20242b'))
    painter.drawPixmap(QPoint(x, y), patch)
    center = QPoint(x + patch.width() // 2, y + patch.height() // 2)
    painter.setPen(QPen(QColor('#38bdf8'), 1))
    painter.drawLine(center.x(), y, center.x(), y + patch.height() - 1)
    painter.drawLine(x, center.y(), x + width - 1, center.y())
    painter.drawRect(QRect(x, y, width, height).adjusted(0, 0, -1, -1))
    painter.setPen(Qt.GlobalColor.white)
    ratio = screenshot.devicePixelRatio()
    w = round((selection.x() + selection.width()) * ratio) - round(selection.x() * ratio)
    h = round((selection.y() + selection.height()) * ratio) - round(selection.y() * ratio)
    label = f'{w} × {h} px' if not selection.isEmpty() else '7× · 드래그하여 선택'
    painter.drawText(QRect(x, y + patch.height(), width, 26), Qt.AlignmentFlag.AlignCenter, label)
    painter.restore()
