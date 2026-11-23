"""Read Mokuro Browser's page ledger without changing its database."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

DEFAULT_HISTORY = Path.home()/'.local/share/mokuro-browser/reading-history.sqlite3'


def sync_history(store, filename):
    path = Path(filename).expanduser().resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.2)) as source:
        rows = source.execute('SELECT id,title,scanned_at,text,deleted FROM pages ORDER BY scanned_at,id').fetchall()
    changed = 0
    store.batching = True
    try:
        with store.db:
            for identifier, title, captured, text, deleted in rows:
                key = 'mokuro-browser:'+identifier
                if deleted:
                    changed += store.db.execute('DELETE FROM readings WHERE key=?',(key,)).rowcount
                    store.db.execute('DELETE FROM reading_texts WHERE key=?',(key,))
                    continue
                stamp = datetime.fromtimestamp(captured, timezone.utc).isoformat()
                label = 'Mokuro Browser · '+(title.strip() or 'Browser reading')
                before = store.db.execute('SELECT r.source,r.characters,t.text FROM readings r LEFT JOIN reading_texts t USING(key) WHERE r.key=?',(key,)).fetchone()
                updated = store.record(key,text,label,stamp)
                changed += int(updated or (before is not None and before[2] != text))
    finally:
        store.batching = False
    return changed


def fingerprint(filename):
    path = Path(filename).expanduser()
    result = []
    for file in (path,Path(str(path)+'-wal')):
        try:
            stat = file.stat(); result.append((stat.st_mtime_ns,stat.st_size))
        except FileNotFoundError:
            result.append(None)
    return tuple(result)
