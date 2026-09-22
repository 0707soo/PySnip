"""Small Windows screenshot and pin utility. Run with python main.py."""
from version import __version__
from datetime import datetime
from pathlib import Path
import sys
import json

if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
    # Windowed executables have no stderr; preserve early startup failures.
    sys.stderr = open(sys.argv[2] + '.log', 'w', encoding='utf-8')

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal, QSettings
from PySide6.QtGui import QColor, QCursor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from hotkeys import DEFAULTS, SettingsDialog, WindowsHotkeys, validate_bindings
from ocr_ui import OcrDialog
from portable_settings import open_settings as open_portable_settings


def crop_selection(pixmap, rect):
    """Convert logical selection coordinates to physical screenshot pixels."""
    ratio = pixmap.devicePixelRatio()
    left, top = round(rect.x() * ratio), round(rect.y() * ratio)
    right = round((rect.x() + rect.width()) * ratio)
    bottom = round((rect.y() + rect.height()) * ratio)
    return pixmap.copy(QRect(left, top, right - left, bottom - top))


def drag_rect(start, end, bounds):
    return QRect(min(start.x(), end.x()), min(start.y(), end.y()),
                 abs(end.x() - start.x()), abs(end.y() - start.y())).intersected(bounds)


class CaptureOverlay(QWidget):
    selected = Signal(QPixmap, QPoint)
    cancelled = Signal()

    def __init__(self, screen, screenshot):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.screenshot = screenshot
        self.origin = None
        self.pointer = None
        self.selection = QRect()
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.screenshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if not self.selection.isEmpty():
            painter.save()
            painter.setClipRect(self.selection)
            painter.drawPixmap(self.rect(), self.screenshot)
            painter.restore()
            painter.setPen(QPen(QColor('#38bdf8'), 2))
            painter.drawRect(self.selection.adjusted(0, 0, -1, -1))
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(24, 32, '드래그: 영역 선택 후 고정  ·  Esc / 우클릭: 취소')
        if self.pointer is not None:
            from magnifier import draw_magnifier
            draw_magnifier(painter, self.screenshot, self.pointer, self.rect(), self.selection)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()

    def leaveEvent(self, event):
        self.pointer = None
        self.update()

    def mouseMoveEvent(self, event):
        self.pointer = event.position().toPoint()
        if self.origin is not None:
            self.selection = drag_rect(self.origin, event.position().toPoint(), self.rect())
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        self.selection = drag_rect(self.origin, event.position().toPoint(), self.rect())
        self.origin = None
        if self.selection.width() >= 3 and self.selection.height() >= 3:
            self.selected.emit(crop_selection(self.screenshot, self.selection), self.mapToGlobal(self.selection.topLeft()))
        else:
            self.selection = QRect()
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


class PinWindow(QWidget):
    closed = Signal(object)
    ocr_requested = Signal(QPixmap)
    settings_requested = Signal()
    opacity_requested = Signal(int)
    edit_requested = Signal(object)
    text_edit_requested = Signal(object)

    def __init__(self, pixmap, position):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.pixmap = pixmap
        self.text_card = None
        self.scale = 1.0
        self.locked = False
        self.thumbnail = False
        self.drawing = False
        self.draw_canvas = None
        self.draw_panel = None
        self.palette_store = None
        self.skip_close_confirmation = False
        self.close_prompt = None
        self.border_width = 1
        self.opacity_percent = 100
        self.drag_offset = None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('PySnip — 고정 이미지')
        self.setToolTip('Shift+더블클릭: 썸네일 접기·펼치기')
        self.setMinimumSize(1, 1)
        self.move(position)
        self.resize_image()
        for sequence, callback in [('Ctrl+C', self.copy_image), ('Ctrl+S', self.save_image), ('Ctrl+T', self.extract_text), ('Escape', self.handle_escape), ('Space', self.toggle_drawing), ('Ctrl+Z', self.undo_drawing), ('Ctrl+Y', self.redo_drawing), ('0', self.reset_size), ('Ctrl+L', self.toggle_lock), ('Ctrl+E', lambda: self.edit_requested.emit(self))]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)

    def resize_image(self):
        size = self.pixmap.deviceIndependentSize()
        width = max(1, round(size.width() * self.scale))
        height = max(1, round(size.height() * self.scale))
        if self.thumbnail:
            factor = min(1.0, 160 / width, 160 / height)
            width, height = max(1, round(width * factor)), max(1, round(height * factor))
        self.resize(width + 2 * self.border_width, height + 2 * self.border_width)
        if self.draw_canvas is not None:
            self.draw_canvas.setGeometry(self.rect().adjusted(self.border_width, self.border_width, -self.border_width, -self.border_width))

    def set_opacity_percent(self, value):
        self.opacity_percent = min(100, max(20, int(value)))
        self.setWindowOpacity(self.opacity_percent / 100)

    def set_border_width(self, value):
        self.border_width = min(20, max(0, int(value)))
        self.resize_image()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        border = self.border_width
        if border:
            painter.fillRect(self.rect(), QColor('#38bdf8'))
        painter.drawPixmap(self.rect().adjusted(border, border, -border, -border), self.pixmap)

    def mousePressEvent(self, event):
        if not self.locked and event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if not self.locked and self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.toggle_thumbnail()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def toggle_thumbnail(self):
        self.stop_drawing()
        if self.locked:
            return
        self.thumbnail = not self.thumbnail
        self.drag_offset = None
        self.resize_image()
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag_offset = None

    def wheelEvent(self, event):
        if self.locked or self.drawing:
            return
        delta = event.angleDelta().y()
        if not delta:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.opacity_requested.emit(self.opacity_percent + (5 if delta > 0 else -5))
        elif not self.thumbnail:
            self.scale = min(5.0, max(0.1, self.scale * (1.1 if delta > 0 else 1 / 1.1)))
            self.resize_image()

    def toggle_lock(self):
        self.stop_drawing()
        self.locked = not self.locked
        self.drag_offset = None
        self.setWindowTitle('PySnip — 고정 이미지' + (' (잠금)' if self.locked else ''))

    def reset_size(self):
        self.stop_drawing()
        if self.locked:
            return
        self.thumbnail = False
        self.scale = 1.0
        self.resize_image()

    def toggle_drawing(self):
        if self.drawing:
            self.stop_drawing()
            return
        if self.locked or self.close_prompt is not None:
            return
        if self.thumbnail:
            self.toggle_thumbnail()
        if self.draw_canvas is None:
            from annotation_ui import AnnotationCanvas
            from drawing_panel import DrawingPanel
            self.draw_canvas = AnnotationCanvas(self.pixmap, self, inline=True)
            self.draw_canvas.tool = 'pen'
            self.draw_canvas.changed.connect(self.update_drawing)
            self.draw_panel = DrawingPanel(self)
        self.drawing = True
        self.resize_image()
        self.draw_canvas.show()
        self.draw_canvas.raise_()
        self.draw_panel.show_near_pin()
        self.activateWindow()
        self.draw_canvas.setFocus()

    def update_drawing(self):
        self.pixmap = self.draw_canvas.result()
        self.update()

    def stop_drawing(self):
        self.drawing = False
        if self.draw_canvas is not None:
            self.draw_canvas.cancel_stroke()
            self.draw_canvas.hide()
        if self.draw_panel is not None:
            self.draw_panel.hide()

    def undo_drawing(self):
        if self.drawing:
            self.draw_canvas.undo()

    def redo_drawing(self):
        if self.drawing:
            self.draw_canvas.redo()

    def handle_escape(self):
        if self.drawing:
            self.stop_drawing()
        else:
            self.close()

    def hideEvent(self, event):
        self.stop_drawing()
        super().hideEvent(event)

    def replace_text_card(self, card, pixmap):
        self.stop_drawing()
        if self.draw_canvas is not None:
            self.draw_canvas.changed.disconnect(self.update_drawing)
            self.draw_panel.deleteLater()
            self.draw_canvas.deleteLater()
            self.draw_panel = self.draw_canvas = None
        self.text_card = dict(card)
        self.pixmap = pixmap
        self.resize_image()
        self.update()

    def copy_source_text(self):
        if self.text_card is not None:
            QApplication.clipboard().setText(self.text_card['text'])

    def copy_image(self):
        QApplication.clipboard().setPixmap(self.pixmap)

    def extract_text(self):
        self.ocr_requested.emit(self.pixmap)

    def save_image(self):
        filename, _ = QFileDialog.getSaveFileName(self, '이미지 저장', str(Path.home() / f'capture_{datetime.now():%Y%m%d_%H%M%S}.png'), 'PNG 이미지 (*.png)')
        if filename:
            if not filename.lower().endswith('.png'):
                filename += '.png'
            if not self.pixmap.save(filename, 'PNG'):
                QMessageBox.warning(self, '저장 실패', '파일 경로와 쓰기 권한을 확인해 주세요.')

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self.text_card is not None:
            menu.addAction('원문 텍스트 복사', self.copy_source_text)
            menu.addAction('텍스트 카드 편집', lambda: self.text_edit_requested.emit(self))
            menu.addSeparator()
        lock = menu.addAction('이동·크기 잠금 (Ctrl+L)', self.toggle_lock)
        lock.setCheckable(True)
        lock.setChecked(self.locked)
        thumbnail = menu.addAction('썸네일로 접기 (Shift+더블클릭)' if not self.thumbnail else '이미지 펼치기 (Shift+더블클릭)', self.toggle_thumbnail)
        thumbnail.setEnabled(not self.locked)
        drawing = menu.addAction('그리기 완료 (Space)' if self.drawing else '이미지 위에 그리기 (Space)', self.toggle_drawing)
        drawing.setEnabled(not self.locked)
        menu.addAction('이미지 편집 (Ctrl+E)', lambda: self.edit_requested.emit(self))
        menu.addSeparator()
        for label, callback in [('복사 (Ctrl+C)', self.copy_image), ('저장 (Ctrl+S)', self.save_image), ('텍스트 추출 OCR (Ctrl+T)', self.extract_text), ('설정', self.settings_requested.emit), ('원래 크기 (0)', self.reset_size), ('닫기 (Esc)', self.close)]:
            menu.addAction(label, callback)
        menu.exec(event.globalPos())

    def close_without_confirmation(self):
        self.skip_close_confirmation = True
        if self.close_prompt is not None:
            self.close_prompt.reject()
            return  # The original closeEvent resumes and completes the close.
        self.close()

    def closeEvent(self, event):
        if not self.skip_close_confirmation:
            if self.close_prompt is not None:
                event.ignore()
                return
            prompt = QMessageBox(QMessageBox.Icon.Question, '이미지 닫기',
                                 '이 고정 이미지를 닫으시겠습니까?',
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            prompt.button(QMessageBox.StandardButton.Yes).setText('닫기')
            prompt.button(QMessageBox.StandardButton.No).setText('취소')
            prompt.setDefaultButton(QMessageBox.StandardButton.No)
            prompt.setEscapeButton(QMessageBox.StandardButton.No)
            self.close_prompt = prompt
            result = prompt.exec()
            self.close_prompt = None
            prompt.deleteLater()
            if not self.skip_close_confirmation and result != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.stop_drawing()
        self.closed.emit(self)
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, enable_integrations=True, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else open_portable_settings()
        from color_palette import PaletteStore
        self.palette_store = PaletteStore(self.settings, self)
        self.opacity_percent, self.border_width = 100, 1
        self.ocr_language = self.settings.value('OCR/language', 'ko-KR')
        if self.ocr_language not in ('ko-KR', 'en-US'):
            self.ocr_language = 'ko-KR'
        try:
            self.ocr_scale = int(self.settings.value('OCR/retry_scale', 2))
        except (ValueError, TypeError):
            self.ocr_scale = 2
        if self.ocr_scale not in (1, 2, 4):
            self.ocr_scale = 2
        try:
            self.opacity_percent = min(100, max(20, int(self.settings.value('Appearance/opacity', 100))))
            self.border_width = min(20, max(0, int(self.settings.value('Appearance/border', 1))))
        except (ValueError, TypeError, AttributeError):
            self.opacity_percent, self.border_width = 100, 1
        self.bindings = dict(DEFAULTS)
        try:
            candidate = {name: self.settings.value('Hotkeys/' + name, default) for name, default in DEFAULTS.items()}
            validate_bindings(candidate, check_reserved=False)
            self.bindings = candidate
        except (ValueError, TypeError, AttributeError, KeyError):
            pass
        self.restore_pins = str(self.settings.value('Session/restore_pins', False)).lower() in ('true', '1')
        self.session_path = Path(self.settings.fileName()).with_suffix('.session.json')
        self.ocr_auto_copy = str(self.settings.value('OCR/auto_copy', False)).lower() in ('true', '1')
        try:
            self.history_limit = min(999999, max(0, int(self.settings.value('History/limit', 0))))
        except (ValueError, TypeError):
            self.history_limit = 0
        self.closed_pins = []
        self.editors = []
        self.history_action = None
        self.settings_dialog = None
        self.ocr_dialogs = []
        self.hotkey_error = ''
        self.action_buttons = []
        self.tray_actions = []
        self.pins = []
        self.pins_hidden = False
        self.toggle_action = None
        self.overlays = []
        self.capturing = False
        self.restore_main = False
        self.tray = None
        self.hotkeys = None
        self.quitting = False
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(self.start_capture)
        QApplication.instance().aboutToQuit.connect(self.cleanup)
        self.setWindowTitle(f'PySnip {__version__}')
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel(f'PySnip {__version__}')
        title.setStyleSheet('font-size: 28px; font-weight: 700;')
        layout.addWidget(title)
        layout.addWidget(QLabel('화면을 캡처하고, 필요한 곳에 고정하세요.'))
        for label, callback in [('영역 캡처', self.capture), ('클립보드 고정 (이미지·텍스트)', self.pin_clipboard), ('설정', self.open_settings), ('고정 이미지 모두 닫기', self.close_pins), ('종료', self.quit_app)]:
            button = QPushButton(label)
            button.setMinimumHeight(34)
            button.clicked.connect(callback)
            layout.addWidget(button)
            self.action_buttons.append(button)
        self.toggle_button = QPushButton()
        self.toggle_button.setMinimumHeight(34)
        self.toggle_button.clicked.connect(self.toggle_pins)
        layout.insertWidget(4, self.toggle_button)
        self.history_button = QPushButton('마지막 닫은 이미지 복원')
        self.history_button.setMinimumHeight(34)
        self.history_button.clicked.connect(self.restore_closed_pin)
        layout.insertWidget(5, self.history_button)
        self.refresh_history()
        self.status = QLabel('고정 창: 드래그 이동 / 휠 확대·축소\nCtrl+휠 투명도 / 우클릭 메뉴')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setCentralWidget(panel)
        icon = QIcon(str(Path(__file__).resolve().parent / 'assets' / 'pysnip.svg'))
        QApplication.instance().setWindowIcon(icon)
        self.setWindowIcon(icon)
        if enable_integrations:
            self.hotkeys = WindowsHotkeys({'capture': self.capture, 'clipboard': self.pin_clipboard, 'toggle': self.toggle_pins})
            QApplication.instance().installNativeEventFilter(self.hotkeys)
            try:
                self.hotkeys.apply(self.bindings)
            except ValueError as exc:
                self.hotkey_error = str(exc) + '\n전역 단축키가 비활성화되었습니다. 설정에서 변경하세요.'
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray = QSystemTrayIcon(icon, self)
                menu = QMenu(self)
                self.tray_actions = [menu.addAction('영역 캡처', self.capture), menu.addAction('클립보드 고정', self.pin_clipboard)]
                self.toggle_action = menu.addAction('고정 이미지 숨김·복원', self.toggle_pins)
                self.history_action = menu.addAction('마지막 닫은 이미지 복원', self.restore_closed_pin)
                self.refresh_history()
                menu.addAction('설정', self.open_settings)
                menu.addAction('메인 창 열기', self.show_main)
                menu.addSeparator()
                menu.addAction('종료', self.quit_app)
                self.tray.setContextMenu(menu)
                self.tray.activated.connect(self.tray_activated)
                self.tray.show()
        self.refresh_hotkey_labels()
        # Reserve space for the longest supported shortcut before fixing the size.
        if self.settings.status() != QSettings.Status.NoError:
            self.status.setText('PySnip.ini를 읽거나 만들지 못했습니다. 앱 폴더의 쓰기 권한과 INI 형식을 확인하세요.')
        longest_label = '클립보드 고정 (이미지·텍스트)  ·  Ctrl+Alt+Shift+Num9'
        text_width = self.action_buttons[1].fontMetrics().horizontalAdvance(longest_label)
        self.setFixedSize(QSize(max(560, text_width + 80), 420).expandedTo(self.sizeHint()))

    def start(self):
        started_before = str(self.settings.value('Startup/has_started', False)).lower() in ('true', '1')
        self.restore_session()
        self.settings.setValue('Startup/has_started', True)
        self.settings.sync()
        if (not started_before or not self.tray or not self.tray.isVisible()
                or self.settings.status() != QSettings.Status.NoError):
            self.show()

    def restore_session(self):
        if not self.restore_pins:
            return
        from pin_session import load_session
        try:
            records = load_session(self.session_path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.setText(f'고정 이미지 복원 실패: {exc}')
            return
        for pixmap, x, y, scale, locked, thumbnail, text_card in records:
            pin = self.add_pin(pixmap, QPoint(x, y))
            pin.text_card = text_card
            pin.scale = scale
            pin.thumbnail = thumbnail
            if locked:
                pin.toggle_lock()
            pin.resize_image()
            # A removed monitor must not leave restored images inaccessible.
            if not any(screen.availableGeometry().contains(pin.pos()) for screen in QApplication.screens()):
                pin.move(QApplication.primaryScreen().availableGeometry().topLeft() + QPoint(30, 30))

    def open_ocr_settings(self, parent=None):
        dialog = OcrDialog(parent or self)
        self.ocr_dialogs.append(dialog)
        dialog.destroyed.connect(lambda: self.ocr_dialogs.remove(dialog) if dialog in self.ocr_dialogs else None)
        dialog.exec()

    def open_ocr(self, pixmap=None):
        if self.quitting:
            return
        # Reuse an active dialog so Windows language servicing cannot run twice.
        results = [dialog for dialog in self.ocr_dialogs if dialog.image is not None]
        if results:
            dialog = results[0]
            if pixmap is not None:
                dialog.set_image(pixmap.toImage())
            dialog.showNormal()
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = OcrDialog(self, pixmap.toImage() if pixmap is not None else None)
        self.ocr_dialogs.append(dialog)
        dialog.destroyed.connect(lambda: self.ocr_dialogs.remove(dialog) if dialog in self.ocr_dialogs else None)
        dialog.show()

    def refresh_hotkey_labels(self):
        labels = [f"영역 캡처  ·  {self.bindings['capture']}", f"클립보드 고정 (이미지·텍스트)  ·  {self.bindings['clipboard']}"]
        for button, label in zip(self.action_buttons, labels):
            button.setText(label)
        for action, label in zip(self.tray_actions, labels):
            action.setText(label)
        self.refresh_toggle_label()
        if self.tray:
            self.tray.setToolTip(f"PySnip — {self.bindings['capture']} 캡처 / {self.bindings['clipboard']} 클립보드 고정")
        self.status.setText(self.hotkey_error or '고정 창: 드래그 이동 / 휠 확대·축소\nCtrl+휠 투명도 / 우클릭 메뉴')

    def apply_bindings(self, bindings):
        self.apply_settings(bindings, self.opacity_percent, self.border_width)

    def apply_settings(self, bindings, opacity, border, ocr_language=None, ocr_scale=None, ocr_auto_copy=None, restore_pins=None, history_limit=None):
        bindings = {**self.bindings, **bindings}
        validate_bindings(bindings)
        if self.hotkeys:
            self.hotkeys.apply(bindings)
        self.bindings = dict(bindings)
        if ocr_language in ('ko-KR', 'en-US'):
            self.ocr_language = ocr_language
        self.settings.setValue('OCR/language', self.ocr_language)
        if ocr_scale in (1, 2, 4):
            self.ocr_scale = ocr_scale
        self.settings.setValue('OCR/retry_scale', self.ocr_scale)
        if ocr_auto_copy is not None:
            self.ocr_auto_copy = bool(ocr_auto_copy)
        self.settings.setValue('OCR/auto_copy', self.ocr_auto_copy)
        if restore_pins is not None:
            self.restore_pins = bool(restore_pins)
        self.settings.setValue('Session/restore_pins', self.restore_pins)
        if history_limit is not None:
            self.history_limit = min(999999, max(0, int(history_limit)))
        self.settings.setValue('History/limit', self.history_limit)
        self.trim_history()
        if not self.restore_pins:
            self.session_path.unlink(missing_ok=True)
        self.hotkey_error = ''
        for name, value in bindings.items():
            self.settings.setValue('Hotkeys/' + name, value)
        self.update_appearance(opacity, border)
        self.save_settings()

    def update_appearance(self, opacity, border):
        self.opacity_percent = min(100, max(20, int(opacity)))
        self.border_width = min(20, max(0, int(border)))
        for pin in self.pins:
            pin.set_opacity_percent(self.opacity_percent)
            pin.set_border_width(self.border_width)
        self.settings.setValue('Appearance/opacity', self.opacity_percent)
        self.settings.setValue('Appearance/border', self.border_width)

    def set_global_opacity(self, opacity):
        if self.quitting or self.settings_dialog is not None:
            return
        self.update_appearance(opacity, self.border_width)
        try:
            self.save_settings()
        except OSError:
            pass  # The persistence error is displayed in the main status label.

    def save_settings(self):
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            self.hotkey_error = '변경은 적용되었지만 PySnip.ini 저장에 실패했습니다. 앱 폴더의 쓰기 권한을 확인하세요.'
            self.refresh_hotkey_labels()
            raise OSError(self.hotkey_error)
        self.refresh_hotkey_labels()

    def open_settings(self):
        if self.quitting or self.capturing:
            return
        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self)
        self.settings_dialog = dialog
        try:
            dialog.exec()
        finally:
            self.settings_dialog = None
            dialog.deleteLater()

    def show_main(self):
        if self.quitting:
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main()

    def capture(self):
        if self.capturing or self.quitting or self.settings_dialog is not None:
            return
        self.capturing = True
        self.restore_main = self.isVisible() and not self.isMinimized()
        self.hide()
        self.capture_timer.start(180)

    def start_capture(self):
        if self.quitting:
            return
        try:
            # Grab every screen before showing any overlays.
            shots = [(screen, screen.grabWindow(0)) for screen in QApplication.screens()]
            if not shots or any(shot.isNull() for _, shot in shots):
                raise RuntimeError('화면을 읽을 수 없습니다.')
            for screen, shot in shots:
                overlay = CaptureOverlay(screen, shot)
                overlay.selected.connect(self.finish_capture)
                overlay.cancelled.connect(self.cancel_capture)
                self.overlays.append(overlay)
            for overlay in self.overlays:
                overlay.show()
            active = next((o for o in self.overlays if o.geometry().contains(QCursor.pos())), self.overlays[0])
            active.raise_()
            active.activateWindow()
        except Exception as exc:
            self.cancel_capture()
            QMessageBox.warning(self, '캡처 실패', str(exc))

    def clear_overlays(self):
        for overlay in self.overlays:
            overlay.close()
        self.overlays.clear()
        self.capturing = False

    def cancel_capture(self):
        self.clear_overlays()
        if self.restore_main:
            self.show_main()

    def finish_capture(self, pixmap, position):
        if self.quitting:
            return
        self.clear_overlays()
        QApplication.clipboard().setPixmap(pixmap)
        if self.restore_main:
            self.show_main()
        self.add_pin(pixmap, position)

    def add_pin(self, pixmap, position):
        if self.quitting:
            return None
        pin = PinWindow(pixmap, position)
        pin.palette_store = self.palette_store
        pin.set_opacity_percent(self.opacity_percent)
        pin.set_border_width(self.border_width)
        self.pins.append(pin)
        pin.closed.connect(self.remove_pin)
        pin.edit_requested.connect(self.open_editor)
        pin.text_edit_requested.connect(self.open_text_editor)
        pin.ocr_requested.connect(self.open_ocr)
        pin.settings_requested.connect(self.open_settings)
        pin.opacity_requested.connect(self.set_global_opacity)
        if not self.pins_hidden:
            pin.show()
            pin.activateWindow()
        self.refresh_toggle_label()
        return pin

    def remove_pin(self, pin):
        if pin in self.pins:
            if not self.quitting:
                self.closed_pins.append((QPixmap(pin.pixmap), QPoint(pin.pos()), pin.scale, pin.locked, pin.thumbnail, dict(pin.text_card) if pin.text_card else None))
                self.trim_history()
            self.pins.remove(pin)
        if not self.pins:
            self.pins_hidden = False
        self.refresh_toggle_label()

    def refresh_history(self):
        text = f'마지막 닫은 이미지 복원 ({len(self.closed_pins)})'
        self.history_button.setText(text)
        self.history_button.setEnabled(bool(self.closed_pins))
        if self.history_action:
            self.history_action.setText(text)
            self.history_action.setEnabled(bool(self.closed_pins))

    def trim_history(self):
        if self.history_limit:
            self.closed_pins = self.closed_pins[-self.history_limit:]
        self.refresh_history()

    def restore_closed_pin(self):
        if self.quitting or self.capturing or not self.closed_pins:
            return
        pixmap, position, scale, locked, thumbnail, text_card = self.closed_pins.pop()
        if self.pins_hidden:
            self.toggle_pins()
        pin = self.add_pin(pixmap, position)
        pin.text_card = text_card
        pin.scale = scale
        pin.thumbnail = thumbnail
        if locked:
            pin.toggle_lock()
        pin.resize_image()
        if not any(screen.availableGeometry().contains(pin.pos()) for screen in QApplication.screens()):
            pin.move(QApplication.primaryScreen().availableGeometry().topLeft() + QPoint(30, 30))
        self.refresh_history()

    def open_text_editor(self, pin):
        if self.quitting or self.capturing or pin.text_card is None:
            return
        for editor in self.editors:
            if getattr(editor, 'target_pin', None) is pin:
                editor.showNormal()
                editor.raise_()
                editor.activateWindow()
                return
        from text_pin import TextCardDialog
        def apply(card, pixmap):
            if self.quitting or pin not in self.pins:
                return False
            if card == pin.text_card:
                return True
            if pin.draw_canvas is not None and pin.draw_canvas.marks:
                if QMessageBox.question(self, '텍스트 카드 수정',
                        '텍스트를 수정하면 이 카드에 그린 주석이 사라집니다. 수정하시겠습니까?',
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return False
            pin.replace_text_card(card, pixmap)
            return True
        dialog = TextCardDialog(pin, apply, self)
        self.editors.append(dialog)
        pin.closed.connect(dialog.reject)
        dialog.finished.connect(lambda _result: self.editors.remove(dialog) if dialog in self.editors else None)
        dialog.show()

    def open_editor(self, pin):
        if self.quitting or self.capturing:
            return
        from annotation_ui import AnnotationDialog
        dialog = AnnotationDialog(pin.pixmap, self)
        self.editors.append(dialog)
        position = QPoint(pin.pos()) + QPoint(24, 24)
        dialog.pin_requested.connect(lambda pixmap: self.add_edited_pin(pixmap, position))
        dialog.finished.connect(lambda _result: self.editors.remove(dialog) if dialog in self.editors else None)
        dialog.show()

    def add_edited_pin(self, pixmap, position):
        if self.pins_hidden:
            self.toggle_pins()
        self.add_pin(pixmap, position)

    def pin_clipboard(self):
        if self.capturing or self.quitting or self.settings_dialog is not None:
            return
        clipboard = QApplication.clipboard()
        pixmap = clipboard.pixmap()
        text_card = None
        if pixmap.isNull():
            text = clipboard.text()
            if not text.strip():
                QMessageBox.information(self, '클립보드', '클립보드에 이미지나 텍스트가 없습니다.')
                return
            from text_pin import normalize_card, render_card
            try:
                text_card = normalize_card({'text': text})
                pixmap = render_card(text_card)
            except ValueError as exc:
                QMessageBox.warning(self, '텍스트 고정', str(exc))
                return
        pin = self.add_pin(pixmap, QCursor.pos())
        pin.text_card = text_card
        if text_card:
            bounds = (QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()).availableGeometry()
            pin.scale = min(1.0, max(0.1, (bounds.width() - 40) / pixmap.deviceIndependentSize().width()),
                            max(0.1, (bounds.height() - 40) / pixmap.deviceIndependentSize().height()))
            pin.resize_image()
            pin.move(max(bounds.left(), min(pin.x(), bounds.right() - pin.width() + 1)),
                     max(bounds.top(), min(pin.y(), bounds.bottom() - pin.height() + 1)))

    def refresh_toggle_label(self):
        text = f"고정 이미지 모두 {'복원' if self.pins_hidden else '숨기기'}  ·  {self.bindings['toggle']}"
        self.toggle_button.setText(text)
        self.toggle_button.setEnabled(bool(self.pins))
        if self.toggle_action:
            self.toggle_action.setText(text)
            self.toggle_action.setEnabled(bool(self.pins))

    def toggle_pins(self):
        if self.quitting or self.capturing or not self.pins:
            return
        self.pins_hidden = not self.pins_hidden
        for pin in self.pins:
            pin.setVisible(not self.pins_hidden)
        self.refresh_toggle_label()

    def activate_existing(self):
        if self.capturing:
            self.cancel_capture()
        self.show_main()
        if self.settings_dialog is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()

    def close_pins(self):
        if not self.pins:
            return
        if not self.quitting:
            result = QMessageBox.question(self, '고정 이미지 모두 닫기',
                f'고정 이미지 {len(self.pins)}개를 모두 닫으시겠습니까?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if result != QMessageBox.StandardButton.Yes:
                return
        for pin in list(self.pins):
            pin.close_without_confirmation()

    def cleanup(self):
        if self.quitting:
            return
        self.quitting = True
        try:
            if self.restore_pins:
                from pin_session import save_session
                save_session(self.session_path, self.pins)
            else:
                self.session_path.unlink(missing_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, '고정 이미지 저장 실패', f'다음 실행을 위한 이미지를 저장하지 못했습니다.\n{exc}')
        self.capture_timer.stop()
        self.closed_pins.clear()
        for editor in list(self.editors):
            editor.close()
        if self.settings_dialog is not None:
            self.settings_dialog.reject()
        for dialog in list(self.ocr_dialogs):
            dialog.shutdown()
        self.clear_overlays()
        self.close_pins()
        if self.tray:
            self.tray.hide()
        if self.hotkeys:
            self.hotkeys.unregister()
            QApplication.instance().removeNativeEventFilter(self.hotkeys)

    def quit_app(self):
        # Set the exit state before Qt sends close events to all top-level windows.
        self.cleanup()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        elif self.tray and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            self.quit_app()
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('PySnip')
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    from single_instance import SingleInstance
    instance = SingleInstance()
    if not instance.acquire():
        if not instance.notify():
            QMessageBox.warning(None, 'PySnip', '실행 중인 PySnip에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.')
        return 0
    window = MainWindow()
    instance.activated.connect(window.activate_existing)
    app.aboutToQuit.connect(instance.close)
    window.start()
    return app.exec()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        import os
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from release_check import run
        sys.exit(run(sys.argv[2]))
    sys.exit(main())
