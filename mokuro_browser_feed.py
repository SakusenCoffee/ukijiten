"""Follow committed page-history updates in a worker, including offline reads."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import os
from PySide6.QtCore import QObject, QTimer
from mokuro_browser_stats import fingerprint, sync_history
from reading_stats import ReadingStats


def browser_server_running(filename, proc_root=Path('/proc')):
    """Match a running browser server to the selected history database."""
    history=Path(filename).expanduser().resolve()
    default=Path.home()/'.local/share/mokuro-browser/reading-history.sqlite3'
    try:processes=list(proc_root.iterdir())
    except OSError:return False
    for process in processes:
        if not process.name.isdigit():continue
        try:
            if process.stat().st_uid!=os.getuid():continue
            args=(process/'cmdline').read_bytes().decode(errors='replace').rstrip('\0').split('\0')
        except OSError:continue
        module=any(args[i:i+3]==['-m','mokuro_browser','serve'] for i in range(len(args)-2))
        command=bool(args and Path(args[0]).name in ('mokuro-browser','mokuro_browser') and 'serve' in args[1:])
        if not (module or command):continue
        source=str(default)
        for index,value in enumerate(args):
            if value=='--history-file' and index+1<len(args):source=args[index+1]
            elif value.startswith('--history-file='):source=value.split('=',1)[1]
        if Path(source).expanduser().resolve()==history:return True
    return False


class MokuroBrowserFeed(QObject):
    def __init__(self, database, config, changed, parent=None):
        super().__init__(parent)
        self.database,self.changed = database,changed
        self.pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='mokuro-browser-stats')
        self.future = None
        self.fingerprint = None
        self.closed = False
        self.running = False
        self.timer = QTimer(self); self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update)
        self.poll = QTimer(self); self.poll.setInterval(100)
        self.poll.timeout.connect(self.finish)
        self.configure(config)

    def configure(self, config):
        self.config = dict(config)
        self.fingerprint = None
        self.timer.start()
        self.update()

    def update(self):
        if self.closed:return
        running=bool(self.config['enabled'] and browser_server_running(self.config['path']))
        if running!=self.running:
            self.running=running
            QTimer.singleShot(0,self.changed)
        if self.future or not self.config['enabled']:return
        path = self.config['path']
        stamp = fingerprint(path)
        if stamp == self.fingerprint or stamp[0] is None:return
        def import_pages():
            store = ReadingStats(self.database)
            try:
                changed=sync_history(store,path)
                from reading_scripts import backfill_gsm_text
                try:changed+=backfill_gsm_text(store,Path.home()/'.config/GameSentenceMiner/gsm.db')
                except (OSError,sqlite3.Error):pass
                return changed
            finally:store.db.close()
        self.future = (stamp,self.config.copy(),self.pool.submit(import_pages))
        self.poll.start()

    def finish(self):
        if not self.future or not self.future[2].done():return
        stamp,config,future = self.future
        self.future = None; self.poll.stop()
        try:changed = future.result()
        except (OSError,ValueError,sqlite3.Error):return
        if config == self.config:self.fingerprint = stamp
        if changed:self.changed()

    @property
    def is_live(self):
        return bool(self.config['enabled'] and self.running and self.fingerprint)

    def close(self):
        self.closed = True; self.timer.stop(); self.poll.stop()
        self.pool.shutdown(wait=False,cancel_futures=True)
