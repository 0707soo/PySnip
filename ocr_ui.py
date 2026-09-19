"""Asynchronous Windows OCR bridge; screenshots stay on this computer."""
import json
import os
from pathlib import Path
import tempfile
from PySide6.QtGui import QImage, QPainter

from PySide6.QtCore import QObject, QProcess, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

LANGUAGES = {'ko-KR': '한국어', 'en-US': '영어'}


def ocr_dimensions(image, scale, max_dimension):
    if image.isNull():
        raise OSError('OCR할 이미지가 비어 있습니다.')
    limit = max(1, min(4096, int(max_dimension)))
    factor = min(scale, limit / max(image.width(), image.height()))
    return (max(1, round(image.width() * factor)),
            max(1, round(image.height() * factor)), min(64, limit))


def prepare_ocr_image(image, scale, max_dimension):
    width, height, minimum = ocr_dimensions(image, scale, max_dimension)
    scaled = image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    # Add white margins to very narrow crops; do not stretch their aspect ratio.
    prepared = QImage(max(width, minimum), max(height, minimum), QImage.Format.Format_RGB32)
    if prepared.isNull():
        raise OSError('OCR 이미지 메모리를 확보하지 못했습니다.')
    prepared.fill(Qt.GlobalColor.white)
    painter = QPainter(prepared)
    painter.drawImage((prepared.width() - width) // 2, (prepared.height() - height) // 2, scaled)
    painter.end()
    return prepared


def supported_languages(tags):
    tags = {tag.lower() for tag in tags}
    return {'ko-KR': bool(tags & {'ko', 'ko-kr'}),
            'en-US': bool(tags & {'en', 'en-us'})}


class OcrJob(QObject):
    completed = Signal(dict)

    def __init__(self, mode, image=None, language='ko-KR', max_dimension=2600, scale=1, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.folder = tempfile.TemporaryDirectory(prefix='pysnip-ocr-')
        self.process = QProcess(self)
        self.process.finished.connect(self.finish)
        self.process.errorOccurred.connect(self.process_error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)
        self.done = False
        script = Path(__file__).resolve().with_name('ocr_bridge.ps1')
        self.args = ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Mode', mode]
        if image is not None:
            image = prepare_ocr_image(image, scale, max_dimension)
            path = str(Path(self.folder.name) / 'capture.png')
            if not image.save(path, 'PNG'):
                self.folder.cleanup()
                raise OSError('OCR용 이미지를 준비하지 못했습니다.')
            self.args += ['-ImagePath', path, '-Language', language]
        if mode == 'Install':
            self.args += ['-ResultPath', str(Path(self.folder.name) / 'result.json')]

    def start(self):
        powershell = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
        self.process.start(powershell, self.args)
        if self.mode != 'Install':
            self.timer.start(60000)

    def finish(self, exit_code, exit_status):
        if self.done:
            return
        output = bytes(self.process.readAllStandardOutput()).decode('utf-8-sig', errors='replace').strip()
        try:
            result = json.loads(output)
            if not isinstance(result, dict) or 'ok' not in result:
                raise ValueError('Invalid OCR result')
        except (ValueError, TypeError):
            details = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace').strip()
            result = {'ok': False, 'error': details or f'OCR 도우미가 올바른 응답을 반환하지 않았습니다. (코드 {exit_code})'}
        self.complete(result)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.complete({'ok': False, 'error': 'Windows PowerShell을 실행하지 못했습니다. Windows 10 이상이 필요합니다.'})

    def timeout(self):
        self.stop()
        self.completed.emit({'ok': False, 'error': 'OCR 응답 시간이 초과되었습니다. 더 작은 영역으로 다시 시도해 주세요.'})

    def complete(self, result):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        self.folder.cleanup()
        self.completed.emit(result)

    def stop(self):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(2000)
        # Elevated Windows servicing must not be killed during app shutdown.
        self.folder.cleanup()


class OcrDialog(QDialog):
    def __init__(self, parent, image=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('텍스트 추출 · Windows OCR' if image is not None else 'OCR 언어 활성화')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.image = image
        self.preferred_language = getattr(parent, 'ocr_language', 'ko-KR')
        self.job = None
        self.available = {}
        self.max_dimension = 2600
        self.stopping = False
        self.after_install = ''
        self.attempt_scales = [1]
        self.attempt_index = 0
        layout = QVBoxLayout(self)
        self.status = QLabel('Windows OCR 언어를 확인하고 있습니다…')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(64)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.language = QComboBox()
        for tag, label in LANGUAGES.items():
            self.language.addItem(label, tag)
        self.language.setCurrentIndex(max(0, self.language.findData(self.preferred_language)))
        self.language.currentIndexChanged.connect(self.update_buttons)
        row.addWidget(self.language)
        self.recognize = QPushButton('텍스트 추출')
        self.recognize.clicked.connect(self.extract)
        row.addWidget(self.recognize)
        layout.addLayout(row)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText('인식된 텍스트를 여기에서 수정하고 복사할 수 있습니다.')
        self.text.setVisible(image is not None)
        layout.addWidget(self.text)
        self.copy = QPushButton('전체 복사')
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        self.copy.setVisible(image is not None)
        self.copy.setEnabled(False)
        self.text.textChanged.connect(lambda: self.copy.setEnabled(bool(self.text.toPlainText())))
        layout.addWidget(self.copy)
        self.install = QPushButton('한국어·영어 활성화 (관리자 권한)')
        self.install.clicked.connect(self.install_languages)
        layout.addWidget(self.install)
        self.refresh = QPushButton('설치 상태 다시 확인')
        self.refresh.clicked.connect(self.check_status)
        layout.addWidget(self.refresh)
        hint = QLabel('언어 설치에는 인터넷 연결과 Windows 관리자 승인(UAC)이 필요합니다.\nOCR은 이 PC에서 처리하며 이미지를 외부 서버로 보내지 않습니다.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.language.hide()
        self.recognize.hide()
        self.copy.hide()
        if image is not None:
            self.status.hide()
            self.install.hide()
            self.refresh.hide()
            hint.hide()
            self.text.setPlaceholderText('텍스트를 추출하고 있습니다…')
        self.setFixedSize(QSize(620, 440 if image is not None else 260).expandedTo(self.sizeHint()))
        self.update_buttons()
        QTimer.singleShot(0, self.check_status)

    def set_image(self, image):
        if self.job is not None:
            self.job.stop()
            self.job.deleteLater()
            self.job = None
        self.image = image
        self.preferred_language = getattr(self.parent(), 'ocr_language', 'ko-KR')
        self.language.setCurrentIndex(max(0, self.language.findData(self.preferred_language)))
        self.text.clear()
        self.text.setPlaceholderText('텍스트를 추출하고 있습니다…')
        self.check_status()

    def notice(self, message):
        self.status.setText(message)
        if self.image is not None:
            self.text.setPlaceholderText(message)

    def update_buttons(self):
        busy = self.job is not None
        self.language.setEnabled(not busy)
        self.recognize.setEnabled(not busy and self.image is not None and self.available.get(self.language.currentData(), False))
        self.install.setEnabled(not busy and not all(self.available.get(tag, False) for tag in LANGUAGES))
        self.refresh.setEnabled(not busy)

    def run_job(self, mode, callback, **kwargs):
        if self.job is not None or self.stopping:
            return
        try:
            job = OcrJob(mode, parent=self, **kwargs)
        except OSError as exc:
            self.notice(str(exc))
            return
        self.job = job
        def finished(result):
            self.job = None
            job.deleteLater()
            if not self.stopping:
                callback(result)
                self.update_buttons()
        job.completed.connect(finished)
        self.update_buttons()
        job.start()

    def check_status(self):
        if self.job is not None or self.stopping:
            return
        self.status.setText('Windows OCR 언어를 확인하고 있습니다…')
        self.run_job('Status', self.show_status)

    def show_status(self, result):
        if not result.get('ok'):
            self.available = {}
            self.notice('확인 실패: ' + result.get('error', '알 수 없는 오류'))
            return
        self.available = supported_languages(result.get('languages', []))
        self.max_dimension = max(1, int(result.get('max_dimension', 2600)))
        states = [f"{label}: {'사용 가능' if self.available[tag] else '설치 필요'}" for tag, label in LANGUAGES.items()]
        self.status.setText(' / '.join(states) + self.after_install)
        self.after_install = ''
        if not self.available.get(self.language.currentData()):
            for i in range(self.language.count()):
                if self.available.get(self.language.itemData(i)):
                    self.language.setCurrentIndex(i)
                    break
        if self.image is not None:
            if self.available.get(self.language.currentData()):
                self.extract()
            else:
                self.notice('사용 가능한 OCR 언어가 없습니다. 설정 → OCR 언어 활성화에서 설치해 주세요.')

    def extract(self):
        self.attempt_scales = []
        self.attempt_index = 0
        sizes = set()
        try:
            retry_scale = getattr(self.parent(), 'ocr_scale', 2)
            if retry_scale not in (1, 2, 4):
                retry_scale = 2
            for scale in (1, retry_scale):
                dimensions = ocr_dimensions(self.image, scale, self.max_dimension)
                if dimensions not in sizes:
                    sizes.add(dimensions)
                    self.attempt_scales.append(scale)
        except OSError as exc:
            self.notice(str(exc))
            return
        self.notice('텍스트를 추출하고 있습니다…')
        self.recognize_attempt()

    def recognize_attempt(self):
        if self.stopping:
            return
        self.run_job('Recognize', self.show_text, image=self.image,
                     language=self.language.currentData(), max_dimension=self.max_dimension,
                     scale=self.attempt_scales[self.attempt_index])

    def show_text(self, result):
        if self.stopping:
            return
        retryable = ((result.get('ok') and not result.get('text', '').strip())
                     or (not result.get('ok') and result.get('stage') == 'recognize'))
        if retryable and self.attempt_index + 1 < len(self.attempt_scales) and not self.stopping:
            self.attempt_index += 1
            self.notice('텍스트를 추출하고 있습니다…')
            self.recognize_attempt()
            return
        if result.get('ok'):
            self.text.setPlainText(result.get('text', ''))
            if result.get('text', '').strip() and getattr(self.parent(), 'ocr_auto_copy', False):
                QApplication.clipboard().setText(result['text'])
            self.notice('' if result.get('text', '').strip() else '텍스트를 찾지 못했습니다. 글자가 포함된 선명한 영역을 캡처해 주세요.')
        else:
            self.notice('추출 실패: ' + result.get('error', '알 수 없는 오류'))

    def install_languages(self):
        self.status.setText('Windows 관리자 승인 창에서 허용해 주세요.\n언어 기능을 설치하고 있습니다. 몇 분 이상 걸릴 수 있습니다.')
        self.run_job('Install', self.install_finished)

    def install_finished(self, result):
        if result.get('ok'):
            self.after_install = '\nWindows에서 재시작이 필요하다고 보고했습니다.' if result.get('restart') else '\n언어 기능 설치가 완료되었습니다.'
            self.check_status()
        else:
            self.status.setText('활성화 실패 또는 승인 취소: ' + result.get('error', '알 수 없는 오류') + '\n인터넷 연결·Windows Update 정책을 확인한 뒤 다시 시도하세요.')

    def shutdown(self):
        self.stopping = True
        if self.job is not None:
            self.job.stop()
            self.job = None
        self.close()

    def closeEvent(self, event):
        if self.job is not None and self.job.mode == 'Install' and not self.stopping:
            self.status.setText('언어 설치가 진행 중입니다. 완료 후 이 창을 닫아 주세요.')
            event.ignore()
            return
        self.stopping = True
        if self.job is not None:
            self.job.stop()
            self.job = None
        event.accept()

    def reject(self):
        # Escape follows the same cancellation/installation guard as the X button.
        self.close()
