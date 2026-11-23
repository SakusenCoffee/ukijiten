"""Background review-time updates from synced server or desktop Anki data."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import time

def json_fingerprint(config):
    return json.dumps(config, sort_keys=True)
from PySide6.QtCore import QObject, QTimer
from reading_stats import ReadingStats
from anki_stats import import_review_time, refresh_anki
import copy


class AnkiStatsFeed(QObject):
    def __init__(self, database, paths, changed, parent=None):
        super().__init__(parent)
        self.database, self.paths, self.changed = database, paths, changed
        self.status = 'Checking Anki'
        self.config = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='anki-stats')
        self.future = None
        self.fingerprint = None
        self.pending_fingerprint = None
        self.closed = False
        self.timer = QTimer(self);self.timer.setInterval(30000);self.timer.timeout.connect(self.update);self.timer.start()
        self.poll = QTimer(self);self.poll.setInterval(100);self.poll.timeout.connect(self.finish)
        QTimer.singleShot(0,self.update)

    def update(self):
        if self.closed or self.future:
            return
        config = copy.deepcopy(self.config)
        if config and not config['enabled']:
            self.status = 'Anki disabled'
            return
        fingerprint=[]
        for source in self.paths:
            for suffix in ('','-wal'):
                path=Path(str(source)+suffix).expanduser()
                try:
                    stat=path.stat();fingerprint.append((str(path),stat.st_mtime_ns,stat.st_size))
                except OSError:
                    pass
        if config:
            fingerprint.append(json_fingerprint(config))
            if config['backend'] == 'connect':
                fingerprint.append(time.monotonic() // 30)
        if fingerprint==self.fingerprint:
            return
        self.pending_fingerprint=fingerprint
        def work():
            store=ReadingStats(self.database)
            try:
                return refresh_anki(store, config) if config else import_review_time(store,self.paths)
            finally:
                store.db.close()
        self.future=self.executor.submit(work)
        self.poll.start()

    def finish(self):
        if not self.future or not self.future.done():
            return
        self.poll.stop()
        future,self.future=self.future,None
        try:
            result=future.result()
            self.fingerprint=self.pending_fingerprint
            self.status='Anki updated · ' + ('AnkiConnect' if result['source'] == 'AnkiConnect' else 'collections')
        except Exception as error:
            self.fingerprint=self.pending_fingerprint
            self.status=str(error) if isinstance(error, ValueError) else 'Waiting for Anki review history'
        self.changed()
        self.update()

    def close(self):
        self.closed=True;self.timer.stop();self.poll.stop()
        self.executor.shutdown(wait=False,cancel_futures=True)
