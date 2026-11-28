"""Read-only hover lookup into the app's existing SQLite dictionaries."""
import json
import sqlite3
from time import monotonic
from async_lookup import AsyncLookup, prepare_lookup
from async_lookup import DB_PATH


def hover_lookup(payload, cancelled, path=DB_PATH, enabled_ids=None):
    candidates=json.loads(payload)[:512]
    terms=list(dict.fromkeys(c['text'] for c in candidates if isinstance(c.get('text'),str) and len(c['text'])<=64))
    if not terms or cancelled.is_set() or enabled_ids == []:return []
    db=sqlite3.connect(f'{path.as_uri()}?mode=ro',uri=True,timeout=1)
    deadline=monotonic()+3
    try:
        db.set_progress_handler(lambda:cancelled.is_set() or monotonic()>deadline,2000)
        db.execute('BEGIN')
        slots=','.join('?' for _ in terms)
        length={}
        for candidate in candidates:length[candidate['text']]=max(length.get(candidate['text'],0),candidate['length'])
        db.create_function('source_length',2,lambda term,reading:max(length.get(term,0),length.get(reading,0)))
        if enabled_ids is not None:
            ranks={did:i for i,did in enumerate(enabled_ids)}
            db.create_function('hover_order',1,lambda did:ranks.get(did,len(ranks)))
        order='d.sort_order' if enabled_ids is None else 'hover_order(d.id)'
        condition='d.enabled=1' if enabled_ids is None else 'd.id IN (' + ','.join('?' for _ in enabled_ids) + ')'
        # Rank small metadata first; decode only definitions that will be shown.
        rows=db.execute(f"""WITH candidates AS (SELECT rowid FROM entries WHERE term IN ({slots})
            UNION SELECT rowid FROM entries WHERE reading IN ({slots}))
            SELECT e.rowid,e.term,e.reading,d.id,d.title FROM candidates c
            JOIN entries e ON e.rowid=c.rowid JOIN dictionaries d ON d.id=e.dictionary_id WHERE {condition}
            ORDER BY source_length(e.term,e.reading) DESC,{order},d.id,e.rowid LIMIT 160""",(*terms,*terms,*(enabled_ids or []))).fetchall()
        best=max((max(length.get(r[1],0),length.get(r[2],0)) for r in rows),default=0)
        selected=[r for r in rows if max(length.get(r[1],0),length.get(r[2],0))==best][:40]
        if not selected:
            return []
        ids = [row[0] for row in selected]
        definitions = dict(db.execute('SELECT rowid,glossary FROM entries WHERE rowid IN ('
                                      + ','.join('?' for _ in ids) + ')', ids))
        return [(term, reading, definitions[rid], did, title)
                for rid, term, reading, did, title in selected]
    finally:db.close()


class HoverLookup(AsyncLookup):
    def submit(self,query):
        from threading import Event
        self.cancel()
        self.cancelled=Event()
        self.query=query
        ids=self.enabled_ids_provider() if hasattr(self,'enabled_ids_provider') else None
        selection=self.metadata_selection_provider()
        self.pending=self.executor.submit(prepare_lookup,hover_lookup,query,self.cancelled,self.metadata_cache,selection,enabled_ids=ids)
        self.watch()
