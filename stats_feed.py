"""Nonblocking, reconnecting GSM subscriber. Never binds GSM's listening port."""
import json
from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtWebSockets import QWebSocket


class StatsFeed(QObject):
    def __init__(self, store, changed, parent=None, url='ws://127.0.0.1:55000/ws/texthooker'):
        super().__init__(parent)
        self.store, self.changed, self.url = store, changed, url
        self.status = 'Connecting'
        self.socket = QWebSocket(parent=self)
        self.socket.setMaxAllowedIncomingMessageSize(8 * 1024 * 1024)
        self.retry = QTimer(self)
        self.retry.setSingleShot(True)
        self.retry.setInterval(3000)
        self.retry.timeout.connect(self.connect_feed)
        self.refresh = QTimer(self)
        self.refresh.setSingleShot(True)
        self.refresh.setInterval(250)
        self.refresh.timeout.connect(self.changed)
        self.socket.connected.connect(self.connected)
        self.socket.disconnected.connect(self.disconnected)
        self.socket.errorOccurred.connect(lambda *_: self.disconnected())
        self.socket.textMessageReceived.connect(self.message)
        QTimer.singleShot(0, self.connect_feed)

    def connect_feed(self):
        if not self.store.preference('capture', True):
            self.status = 'Paused'
            self.changed()
            return
        self.socket.open(QUrl(self.url))

    def connected(self):
        self.retry.stop()
        self.status = 'Live · ' + QUrl(self.url).host() + ':' + str(QUrl(self.url).port(55000))
        if QUrl(self.url).path() == '/ws/texthooker':
            self.socket.sendTextMessage(json.dumps({'event': 'text_v2_snapshot_request', 'max_lines': 1000}))
        self.changed()

    def disconnected(self):
        self.status = 'Waiting for texthooker' if self.store.preference('capture', True) else 'Paused'
        if self.store.preference('capture', True):
            self.retry.start()
        self.changed()

    def message(self, text):
        if not self.store.preference('capture', True):
            return
        try:
            self.store.ingest(text)
        except (ValueError, TypeError, OverflowError):
            return
        if not self.refresh.isActive():
            self.refresh.start()

    def toggle(self, enabled):
        self.store.set_preference('capture', enabled)
        self.retry.stop()
        self.socket.abort()
        if enabled:
            self.connect_feed()
        else:
            self.status = 'Paused'
            self.changed()

    def configure(self, url, enabled):
        self.url = url
        self.toggle(enabled)

    def close(self):
        self.retry.stop()
        self.refresh.stop()
        self.socket.abort()
        self.retry.stop()
