"""Optional Linux mouse-button notifications; no keyboard or motion is retained."""
import os
import select
from threading import Event, Thread
from time import monotonic
from PySide6.QtCore import QObject, Signal


class ButtonPackets:
    def __init__(self):
        self.buffer = bytearray()
        self.buttons = 0

    def feed(self, data):
        self.buffer.extend(data)
        presses = 0
        while len(self.buffer) >= 3:
            buttons = self.buffer[0] & 7
            del self.buffer[:3]
            if buttons & ~self.buttons:
                presses += 1
            self.buttons = buttons
        return presses


class PopupClicks(QObject):
    pressed = Signal(float)

    def __init__(self, parent=None, enabled=True):
        super().__init__(parent)
        self.stop = Event()
        self.thread = None
        self.available = False
        if not enabled:
            return
        try:
            descriptor = os.open('/dev/input/mice', os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return
        self.available = True
        self.thread = Thread(target=self.read, args=(descriptor,), daemon=True, name='popup-clicks')
        self.thread.start()

    def read(self, descriptor):
        packets = ButtonPackets()
        try:
            while not self.stop.is_set():
                if not select.select([descriptor], [], [], .1)[0]:
                    continue
                data = os.read(descriptor, 192)
                if not data:
                    break
                for _ in range(packets.feed(data)):
                    self.pressed.emit(monotonic())
        except OSError:
            pass
        finally:
            os.close(descriptor)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
