"""File contribution ownership: removing an import preserves overlapping sources."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from reading_stats import ReadingStats
from history_import import import_manga, import_gsm


def initialize(store):
    store.db.executescript('''
        CREATE TABLE IF NOT EXISTS import_assets(id TEXT PRIMARY KEY,name TEXT,path TEXT,kind TEXT);
        CREATE TABLE IF NOT EXISTS asset_rows(asset TEXT,key TEXT,payload TEXT,rank REAL,PRIMARY KEY(asset,key));
        CREATE INDEX IF NOT EXISTS asset_key ON asset_rows(key);
        CREATE TABLE IF NOT EXISTS asset_baseline(key TEXT PRIMARY KEY,payload TEXT,rank REAL);
        CREATE TABLE IF NOT EXISTS asset_projection(key TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE IF NOT EXISTS asset_refreshes(asset TEXT PRIMARY KEY,changed REAL);
    ''')
    if not store.preference('import_assets_migrated',False):
        rows=store.db.execute("SELECT * FROM readings WHERE key LIKE 'manga:%'").fetchall()
        if rows:
            versions=store.preference('manga_volume_versions',{})
            with store.db:
                store.db.execute('INSERT OR IGNORE INTO import_assets VALUES (?,?,?,?)',('legacy:mokuro','Previously imported Mokuro history','','mokuro'))
                for row in rows:
                    payload=json.dumps(row)
                    store.db.execute('INSERT OR IGNORE INTO asset_rows VALUES (?,?,?,?)',('legacy:mokuro',row[0],payload,versions.get(row[0].split(':')[1],row[7])))
                    store.db.execute('INSERT OR IGNORE INTO asset_projection VALUES (?,?)',(row[0],payload))
        store.set_preference('import_assets_migrated',True)
    # Old generic imports have a digest but no retained filename.
    for (digest,) in store.db.execute('SELECT digest FROM imports').fetchall():
        identifier='file:'+digest
        if store.db.execute('SELECT 1 FROM import_assets WHERE id=?',(identifier,)).fetchone():continue
        rows=store.db.execute('SELECT * FROM readings WHERE substr(key,1,?)=?',(len('import:'+digest+':'),'import:'+digest+':')).fetchall()
        if rows:
            with store.db:
                store.db.execute('INSERT INTO import_assets VALUES (?,?,?,?)',(identifier,'Imported file · '+digest[:8],'','files'))
                for row in rows:
                    payload=json.dumps(row)
                    store.db.execute('INSERT OR IGNORE INTO asset_rows VALUES (?,?,?,?)',(identifier,row[0],payload,row[7]))
                    store.db.execute('INSERT OR IGNORE INTO asset_projection VALUES (?,?)',(row[0],payload))


def list_assets(store):
    initialize(store)
    result=[]
    for identifier,name,path,kind in store.db.execute('SELECT * FROM import_assets ORDER BY name,id'):
        if kind in ('jpdb','renshuu'):
            study=[json.loads(row[0]) for row in store.db.execute('SELECT payload FROM study_asset_rows WHERE asset=?',(identifier,))]
            result.append(dict(id=identifier,name=name,path=path,kind=kind,characters=0,seconds=0,reviews=sum(row[3] for row in study),activity_days=len({row[2] for row in study})));continue
        totals=store.db.execute("SELECT payload FROM asset_rows WHERE asset=?",(identifier,)).fetchall()
        records=[json.loads(row[0]) for row in totals]
        result.append(dict(id=identifier,name=name,path=path,kind=kind,characters=sum(r[3] for r in records),seconds=sum(r[4] for r in records)))
    return result


def project(store, keys):
    keys=set(keys)
    volumes={key.split(':')[1] for key in keys if key.startswith('manga:')}
    ranks={}
    owners={}
    for volume in volumes:
        prefix='manga:'+volume+':'
        for table in ('asset_rows','asset_baseline','readings'):
            keys.update(row[0] for row in store.db.execute(f'SELECT key FROM {table} WHERE substr(key,1,?)=?',(len(prefix),prefix)))
        row=store.db.execute('SELECT MAX(rank) FROM (SELECT rank FROM asset_rows WHERE substr(key,1,?)=? UNION ALL SELECT rank FROM asset_baseline WHERE substr(key,1,?)=?)',(len(prefix),prefix,len(prefix),prefix)).fetchone()
        ranks[volume]=row[0]
        snapshots=store.db.execute('''SELECT a.asset,MAX(a.rank),COALESCE(f.changed,0)
            FROM asset_rows a LEFT JOIN asset_refreshes f ON f.asset=a.asset
            WHERE substr(a.key,1,?)=? GROUP BY a.asset''',(len(prefix),prefix)).fetchall()
        baseline=store.db.execute('SELECT MAX(rank) FROM asset_baseline WHERE substr(key,1,?)=?',(len(prefix),prefix)).fetchone()[0]
        if baseline is not None:snapshots.append(('baseline',baseline,-1))
        if snapshots:owners[volume]=max(snapshots,key=lambda row:(row[1],row[2],row[0]))[0]
    for key in keys:
        if store.db.execute('SELECT 1 FROM reading_deleted WHERE key=?',(key,)).fetchone():
            store.db.execute('DELETE FROM readings WHERE key=?',(key,));store.db.execute('DELETE FROM asset_projection WHERE key=?',(key,));continue
        current=store.db.execute('SELECT * FROM readings WHERE key=?',(key,)).fetchone()
        previous=store.db.execute('SELECT payload FROM asset_projection WHERE key=?',(key,)).fetchone()
        # A live feed may have revised this line since an import last touched it.
        if current and (not previous or json.loads(previous[0])!=list(current)):
            rank=float(store.preference('manga_volume_versions',{}).get(key.split(':')[1],current[7]))
            store.db.execute('INSERT OR REPLACE INTO asset_baseline VALUES (?,?,?)',(key,json.dumps(current),rank))
        if key.startswith('manga:') and key.split(':')[1] in owners:
            owner=owners[key.split(':')[1]]
            candidates=store.db.execute('SELECT payload,rank FROM asset_baseline WHERE key=?',(key,)).fetchall() if owner=='baseline' else store.db.execute('SELECT payload,rank FROM asset_rows WHERE key=? AND asset=?',(key,owner)).fetchall()
        else:candidates=store.db.execute('SELECT payload,rank FROM asset_rows WHERE key=? UNION ALL SELECT payload,rank FROM asset_baseline WHERE key=?',(key,key)).fetchall()
        if key.startswith('manga:') and ranks.get(key.split(':')[1]) is not None:
            candidates=[row for row in candidates if row[1]>=ranks[key.split(':')[1]]]
        if candidates:
            payload,_=max(candidates,key=lambda row:row[1])
            row=json.loads(payload)
            store.db.execute('INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?,?)',row)
            store.db.execute('INSERT OR REPLACE INTO asset_projection VALUES (?,?)',(key,payload))
        else:
            store.db.execute('DELETE FROM readings WHERE key=?',(key,))
            store.db.execute('DELETE FROM reading_texts WHERE key=?',(key,))
            store.db.execute('DELETE FROM asset_projection WHERE key=?',(key,))


def ingest(store, identifier, name, path, kind, rows, versions=None):
    initialize(store)
    keys={row[0] for row in rows}
    keys.update(row[0] for row in store.db.execute('SELECT key FROM asset_rows WHERE asset=?',(identifier,)))
    with store.db:
        # Capture the base before overwriting previous ownership.
        project(store,keys)
        store.db.execute('INSERT OR REPLACE INTO import_assets VALUES (?,?,?,?)',(identifier,name,str(path),kind))
        store.db.execute('INSERT OR REPLACE INTO asset_refreshes VALUES (?,?)',(identifier,time.time()))
        store.db.execute('DELETE FROM asset_rows WHERE asset=?',(identifier,))
        for row in rows:
            rank=float((versions or {}).get(row[0].split(':')[1],row[7]))
            if row[0].startswith('ttsu:') and path:rank=Path(path).stat().st_mtime
            store.db.execute('INSERT INTO asset_rows VALUES (?,?,?,?)',(identifier,row[0],json.dumps(row),rank))
        project(store,keys)
    return len(rows)


def remove(store, identifier):
    initialize(store)
    asset=store.db.execute('SELECT * FROM import_assets WHERE id=?',(identifier,)).fetchone()
    if not asset:raise ValueError('Imported file not found.')
    if asset[3] in ('jpdb','renshuu'):
        from study_imports import project_study
        keys={row[0] for row in store.db.execute('SELECT key FROM study_asset_rows WHERE asset=?',(identifier,))}
        with store.db:
            store.db.execute('DELETE FROM study_asset_rows WHERE asset=?',(identifier,));store.db.execute('DELETE FROM import_assets WHERE id=?',(identifier,));project_study(store,keys)
        return {'path':asset[2],'kind':asset[3]}
    keys={row[0] for row in store.db.execute('SELECT key FROM asset_rows WHERE asset=?',(identifier,))}
    with store.db:
        project(store,keys)
        store.db.execute('DELETE FROM asset_rows WHERE asset=?',(identifier,))
        store.db.execute('DELETE FROM import_assets WHERE id=?',(identifier,))
        if identifier.startswith('file:'):
            store.db.execute('DELETE FROM imports WHERE digest=?',(identifier[5:],))
        project(store,keys)
    return {'path':asset[2],'kind':asset[3]}


def import_path(store, filename, kind='files'):
    if kind in ('jpdb','renshuu'):
        from study_imports import import_study_file
        return import_study_file(store,filename,kind)
    path=Path(filename).expanduser().resolve()
    with tempfile.TemporaryDirectory() as directory:
        scratch=ReadingStats(Path(directory)/'stats.db')
        try:
            scratch.set_preference('day_cutoff_hour',store.day_cutoff_hour())
            if kind=='gsm_history':import_gsm(scratch,path)
            elif kind=='mokuro':
                data=json.loads(path.read_text())
                if isinstance(data,dict):data=[data] if 'volumes' in data else [{'volumes':data}]
                copy=Path(directory)/'progress.json';copy.write_text(json.dumps(data));import_manga(scratch,copy)
            else:scratch.import_file(path)
            rows=scratch.db.execute('SELECT * FROM readings').fetchall()
            texts=scratch.db.execute('SELECT key,text FROM reading_texts').fetchall()
            versions=scratch.preference('manga_volume_versions',{})
        finally:scratch.db.close()
    if kind=='files':
        with path.open('rb') as source:identifier='file:'+hashlib.file_digest(source,'sha256').hexdigest()
    else:identifier=kind+':'+str(path)
    count=ingest(store,identifier,path.name,path,kind,rows,versions)
    versions_by_key={row[0]:row for row in rows}
    current_texts=[row for row in texts if store.db.execute('SELECT * FROM readings WHERE key=?',(row[0],)).fetchone()==versions_by_key[row[0]]]
    with store.db:store.db.executemany('INSERT OR REPLACE INTO reading_texts VALUES (?,?)',current_texts)
    if kind=='files':
        with store.db:store.db.execute('INSERT OR IGNORE INTO imports VALUES (?)',(identifier[5:],))
    return count


def import_snapshot(store, data, identifier, name,restore_deleted=False):
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'progress.json';path.write_text(json.dumps(data))
        scratch=ReadingStats(Path(directory)/'stats.db')
        try:
            scratch.set_preference('day_cutoff_hour',store.day_cutoff_hour())
            import_manga(scratch,path)
            rows=scratch.db.execute('SELECT * FROM readings').fetchall()
            versions=scratch.preference('manga_volume_versions',{})
        finally:scratch.db.close()
    if restore_deleted:
        # Explicit cloud Refresh is a request to load the source again. Match
        # by volume so deletion markers from an older day cutoff are cleared too.
        with store.db:
            for volume in versions:
                prefix='manga:'+volume+':'
                store.db.execute('DELETE FROM reading_deleted WHERE substr(key,1,?)=?',(len(prefix),prefix))
    return ingest(store,identifier,name,'','mokuro',rows,versions)
