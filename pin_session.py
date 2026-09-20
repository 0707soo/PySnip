"""Portable, atomic storage for pinned images between normal app runs."""
import base64
import json
import math
from pathlib import Path
from PySide6.QtCore import QBuffer, QIODevice, QSaveFile
from PySide6.QtGui import QPixmap


def save_session(path, pins):
    records = []
    for pin in pins:
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        if not pin.pixmap.save(buffer, 'PNG'):
            raise OSError('이미지를 저장하지 못했습니다.')
        records.append({'png': base64.b64encode(bytes(buffer.data())).decode('ascii'),
                        'x': pin.x(), 'y': pin.y(), 'scale': pin.scale,
                        'dpr': pin.pixmap.devicePixelRatio(), 'locked': pin.locked})
    data = json.dumps({'version': 1, 'pins': records}).encode('utf-8')
    output = QSaveFile(str(path))
    if not output.open(QIODevice.WriteOnly):
        raise OSError(output.errorString())
    if output.write(data) != len(data):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())


def load_session(path):
    if not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('pins'), list):
        raise ValueError('지원하지 않는 이미지 복원 파일입니다.')
    result = []
    for item in data['pins']:
        pixmap = QPixmap()
        if not pixmap.loadFromData(base64.b64decode(item['png'], validate=True), 'PNG'):
            raise ValueError('저장된 이미지를 읽지 못했습니다.')
        scale, dpr = float(item['scale']), float(item.get('dpr', 1))
        if not math.isfinite(scale) or not math.isfinite(dpr) or not 0.1 <= scale <= 5 or not 0 < dpr <= 16:
            raise ValueError('저장된 이미지 배율이 올바르지 않습니다.')
        pixmap.setDevicePixelRatio(dpr)
        result.append((pixmap, int(item['x']), int(item['y']), scale, item.get('locked') is True))
    return result
