"""Per-user process lock and local activation channel."""
import hashlib
import os
import tempfile
import time
from pathlib import Path
from PySide6.QtCore import QObject, QLockFile, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, identity='PySnip', parent=None):
        super().__init__(parent)
        scope = str(Path(tempfile.gettempdir()).resolve()) + os.environ.get('USERNAME', '')
        self.name = identity + '-' + hashlib.sha256(scope.encode()).hexdigest()[:24]
        self.lock = QLockFile(str(Path(tempfile.gettempdir()) / (self.name + '.lock')))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.receive)
        self.owner = False

    def acquire(self):
        if not self.lock.tryLock(0):
            return False
        self.owner = True
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.close()
            raise RuntimeError('PySnip activation server could not start')
        return True

    def notify(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(100):
                socket.disconnectFromServer()
                return True
            time.sleep(0.05)
        return False

    def receive(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.close()
            socket.deleteLater()
            self.activated.emit()

    def close(self):
        if self.owner:
            self.server.close()
            self.lock.unlock()
            self.owner = False
