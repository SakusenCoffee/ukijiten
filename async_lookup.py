"""Latest-request-only SQLite lookups, without blocking Qt's UI thread."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
from pathlib import Path
from threading import Event
from time import monotonic
from PySide6.QtCore import QObject, Signal, Qt
from dictionary_search import search_entries
from lookup_cache import ByteCache, database_stamp
from dictionary_render import render_definition
from entry_metadata import MetadataResults

from dictionary_database import DB_PATH
_results = ByteCache()


def lookup(query, cancelled, path=DB_PATH):
    if cancelled.is_set():
        return []
    path = Path(path).resolve()
    stamp = database_stamp(path)
    key = (str(path), stamp, query.strip())
    cached = _results.get(key)
    if cached is not None:
        return list(cached)
    deadline = monotonic() + 8
    db = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=1)
    try:
        db.set_progress_handler(lambda: cancelled.is_set() or monotonic() > deadline, 2000)
        rows = search_entries(db, query)
        if not cancelled.is_set() and database_stamp(path) == stamp:
            stored = tuple(rows)
            size = sys.getsizeof(stored) + sum(sys.getsizeof(row) + sum(sys.getsizeof(v) for v in row) for row in stored)
            _results.put(key, stored, size + sys.getsizeof(query))
        return rows
    finally:
        db.close()


def prepare_lookup(reader, query, cancelled, metadata_cache, selection, **kwargs):
    entries = reader(query, cancelled, **kwargs)
    if metadata_cache is not None and not cancelled.is_set():
        entries = metadata_cache.enrich(entries, selection, cancelled)
    if not isinstance(entries, MetadataResults):
        entries = MetadataResults(entries, {})
    entries.definitions = {}
    for row in entries:
        if cancelled.is_set():
            break
        try:
            entries.definitions[row[2]] = render_definition(row[2])
        except (ValueError, TypeError):
            entries.definitions[row[2]] = None
    return entries


class AsyncLookup(QObject):
    ready = Signal(str, object, str)
    completed = Signal(object)

    def __init__(self, parent, executor=None):
        super().__init__(parent)
        self.owns_executor = executor is None
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='dictionary-lookup')
        self.pending = None
        self.metadata_cache = None
        self.metadata_selection_provider = lambda: ((), ())
        self.cancelled = Event()
        self.completed.connect(self.collect, Qt.ConnectionType.QueuedConnection)

    def watch(self):
        self.pending.add_done_callback(self.notify)

    def notify(self, future):
        try:
            self.completed.emit(future)
        except RuntimeError:
            pass  # The Qt owner may have been deleted during shutdown.

    def submit(self, query):
        self.cancelled.set()
        if self.pending:
            self.pending.cancel()
        self.cancelled = Event()
        self.query = query
        selection = self.metadata_selection_provider()
        self.pending = self.executor.submit(prepare_lookup, lookup, query, self.cancelled, self.metadata_cache, selection)
        self.watch()

    def collect(self, finished):
        if self.pending is finished:
            future, self.pending = self.pending, None
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
        if self.pending:
            self.pending.cancel()
            self.pending = None

    def shutdown(self):
        self.cancel()
        if self.owns_executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
