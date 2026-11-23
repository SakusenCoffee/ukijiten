"""Latest-request-only SQLite lookups, without blocking Qt's UI thread."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Event
from time import monotonic
from PySide6.QtCore import QObject, QTimer, Signal
from yomitan_goldendict import DB_PATH, search_entries


def lookup(query, cancelled, path=DB_PATH):
    if cancelled.is_set():
        return []
    deadline = monotonic() + 8
    db = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=1)
    try:
        db.set_progress_handler(lambda: cancelled.is_set() or monotonic() > deadline, 2000)
        return search_entries(db, query)
    finally:
        db.close()


def prepare_lookup(reader, query, cancelled, metadata_cache, selection, **kwargs):
    entries = reader(query, cancelled, **kwargs)
    if metadata_cache is not None and not cancelled.is_set():
        return metadata_cache.enrich(entries, selection, cancelled)
    return entries


class AsyncLookup(QObject):
    ready = Signal(str, object, str)

    def __init__(self, parent, executor=None):
        super().__init__(parent)
        self.owns_executor = executor is None
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='dictionary-lookup')
        self.pending = None
        self.metadata_cache = None
        self.metadata_selection_provider = lambda: ((), ())
        self.cancelled = Event()
        self.poll = QTimer(self)
        self.poll.setInterval(25)
        self.poll.timeout.connect(self.collect)

    def submit(self, query):
        self.cancelled.set()
        if self.pending:
            self.pending.cancel()
        self.cancelled = Event()
        self.query = query
        selection = self.metadata_selection_provider()
        self.pending = self.executor.submit(prepare_lookup, lookup, query, self.cancelled, self.metadata_cache, selection)
        self.poll.start()

    def collect(self):
        if self.pending and self.pending.done():
            future, self.pending = self.pending, None
            self.poll.stop()
            try:
                entries = future.result()
            except sqlite3.OperationalError as error:
                message = ('Search took too long. Use a more specific word or wildcard pattern.'
                           if 'interrupt' in str(error) else 'Dictionary search could not complete. Try again.')
                self.ready.emit(self.query, [], message)
            else:
                self.ready.emit(self.query, entries, '')

    def cancel(self):
        self.cancelled.set()
        self.poll.stop()
        if self.pending:
            self.pending.cancel()
            self.pending = None

    def shutdown(self):
        self.cancel()
        if self.owns_executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
