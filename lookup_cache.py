"""Small, bounded caches shared by dictionary lookup workers."""
from collections import OrderedDict
from pathlib import Path
from threading import RLock


class ByteCache:
    def __init__(self, max_bytes=16 * 1024 * 1024, max_entries=128):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.bytes = 0
        self.items = OrderedDict()
        self.lock = RLock()

    def get(self, key):
        with self.lock:
            item = self.items.get(key)
            if item is None:
                return None
            self.items.move_to_end(key)
            return item[0]

    def put(self, key, value, size):
        with self.lock:
            previous = self.items.pop(key, None)
            if previous is not None:
                self.bytes -= previous[1]
            if size > self.max_bytes:
                return
            self.items[key] = (value, size)
            self.bytes += size
            while self.bytes > self.max_bytes or len(self.items) > self.max_entries:
                _, (_, removed) = self.items.popitem(last=False)
                self.bytes -= removed


def database_stamp(path):
    """Detect data, enable/order and import changes, including WAL commits."""
    stamp = []
    for suffix in ('', '-wal', '-journal'):
        source = Path(str(path) + suffix)
        try:
            stat = source.stat()
            stamp.append((stat.st_dev, stat.st_ino, stat.st_size,
                          stat.st_mtime_ns, stat.st_ctime_ns))
        except FileNotFoundError:
            stamp.append(None)
    return tuple(stamp)
