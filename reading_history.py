"""Paged history, saved reading text and deletion of local statistics only."""
import csv
from datetime import date,datetime
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from contextlib import closing


def day_expression(store):
    cutoff=store.day_cutoff_hour()
    return f"CASE WHEN r.kind='live' AND r.captured>0 THEN date(r.captured,'unixepoch','localtime','-{cutoff} hours') ELSE r.day END" if cutoff else 'r.day'


def filters(store,values):
    clauses=[];params=[];values=values or {};day=day_expression(store)
    for key,operator in (('from','>='),('to','<='),('day','=')):
        value=values.get(key,'')
        if value:
            try:date.fromisoformat(value)
            except (ValueError,TypeError):raise ValueError('Choose a valid date.')
            clauses.append(day+operator+'?');params.append(value)
    if values.get('source'):
        source=values['source']
        if not isinstance(source,str) or len(source)>1000:raise ValueError('Invalid reading source.')
        aliases=store.preference('source_aliases',{})
        sources=list(dict.fromkeys([source]+[raw for raw,title in aliases.items() if title==source]))
        clauses.append('r.source IN ('+','.join('?' for _ in sources)+')');params.extend(sources)
    if values.get('kind'):
        if values['kind'] not in ('live','import','manual'):raise ValueError('Invalid reading type.')
        clauses.append('r.kind=?');params.append(values['kind'])
    if values.get('search'):
        query=values['search']
        if not isinstance(query,str) or len(query)>500:raise ValueError('Search is too long.')
        query='%'+query.replace('!','!!').replace('%','!%').replace('_','!_')+'%'
        clauses.append("(r.source LIKE ? ESCAPE '!' OR t.text LIKE ? ESCAPE '!')");params.extend((query,query))
    return ' AND '.join(clauses) or '1',params


def query_history(store,request):
    grouped=request.get('grouped',True);limit=max(1,min(100,int(request.get('limit',50))));offset=max(0,int(request.get('offset',0)))
    where,params=filters(store,request);day=day_expression(store)
    base='FROM readings r LEFT JOIN reading_texts t ON t.key=r.key WHERE '+where
    columns=f'{day} AS day,r.source,r.kind,SUM(r.characters) AS characters,SUM(r.seconds) AS seconds,COUNT(*) AS records'
    if grouped:
        group=' GROUP BY '+day+',r.source,r.kind'
        total=store.db.execute('SELECT COUNT(*) FROM (SELECT 1 '+base+group+')',params).fetchone()[0]
        rows=store.db.execute('SELECT '+columns+' '+base+group+' ORDER BY day DESC,r.source,r.kind LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
        names=('day','source','kind','characters','seconds','records')
    else:
        total=store.db.execute('SELECT COUNT(*) '+base,params).fetchone()[0]
        rows=store.db.execute('SELECT r.key,'+day+',r.source,r.kind,r.characters,r.seconds,r.captured,length(COALESCE(t.text,\'\'))>0 '+base+' ORDER BY day DESC,r.captured DESC,r.key LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
        names=('key','day','source','kind','characters','seconds','captured','has_text')
    summary=store.db.execute('SELECT COUNT(*),COALESCE(SUM(r.characters),0),COALESCE(SUM(r.seconds),0) '+base,params).fetchone()
    aliases=store.preference('source_aliases',{});entries=[]
    for row in rows:
        item=dict(zip(names,row));item['title']=aliases.get(item['source'],item['source']);entries.append(item)
    sources=[{'value':row[0],'title':aliases.get(row[0],row[0])} for row in store.db.execute('SELECT DISTINCT source FROM readings ORDER BY source')]
    return dict(entries=entries,total=total,records=summary[0],characters=summary[1],seconds=summary[2],offset=offset,limit=limit,grouped=grouped,sources=sources)


def delete_history(store,selection):
    keys=selection.get('keys',[]);groups=selection.get('groups',[])
    if not isinstance(keys,list) or len(keys)>10000 or not all(isinstance(key,str) and len(key)<2000 for key in keys):raise ValueError('Invalid history selection.')
    if not isinstance(groups,list) or len(groups)>250:raise ValueError('Select up to 250 groups at a time.')
    clauses=[];params=[]
    if selection.get('all_matching') is True:
        where,params=filters(store,selection.get('filter',{}));clauses.append('('+where+')')
    if keys:clauses.append('r.key IN ('+','.join('?' for _ in keys)+')');params.extend(keys)
    for group in groups:
        if not isinstance(group,dict) or not all(group.get(key) for key in ('day','source','kind')):raise ValueError('Invalid history group.')
        clause,values=filters(store,group);clauses.append('('+clause+')');params.extend(values)
    if not clauses:raise ValueError('Select at least one history entry.')
    where=' OR '.join(clauses)
    with store.db:
        store.db.execute('DROP TABLE IF EXISTS temp.history_selection')
        store.db.execute('CREATE TEMP TABLE history_selection(key TEXT PRIMARY KEY)')
        store.db.execute('INSERT INTO history_selection SELECT r.key FROM readings r LEFT JOIN reading_texts t ON t.key=r.key WHERE '+where,params)
        count,characters,seconds=store.db.execute('SELECT COUNT(*),COALESCE(SUM(characters),0),COALESCE(SUM(seconds),0) FROM readings WHERE key IN (SELECT key FROM history_selection)').fetchone()
        # Old local OCR records may have matching GSM IDs; keep their echoes
        # deleted too, so a feed snapshot cannot restore the removed statistics.
        if store.db.execute("SELECT 1 FROM sqlite_master WHERE name='game_ocr_echoes'").fetchone():
            store.db.execute('''INSERT OR IGNORE INTO history_selection SELECT e.remote_key FROM game_ocr_echoes e
                WHERE native_key IN (SELECT key FROM history_selection) AND
                (NOT EXISTS(SELECT 1 FROM readings r WHERE r.key=e.remote_key) OR
                 EXISTS(SELECT 1 FROM gsm_live_texts g WHERE g.key=e.remote_key AND g.digest=e.digest))''')
        store.db.execute("INSERT OR REPLACE INTO reading_deleted SELECT key,strftime('%s','now') FROM history_selection")
        store.db.execute('DELETE FROM readings WHERE key IN (SELECT key FROM history_selection)')
        store.db.execute('DELETE FROM reading_texts WHERE key IN (SELECT key FROM history_selection)')
        store.db.execute('DROP TABLE history_selection')
    return dict(deleted=count,characters=characters,seconds=seconds)


def history_text(store,key,source_paths=()):
    if not isinstance(key,str) or len(key)>2000:raise ValueError('Invalid reading entry.')
    if not store.db.execute('SELECT 1 FROM readings WHERE key=?',(key,)).fetchone():raise ValueError('Reading entry not found.')
    row=store.db.execute('SELECT text FROM reading_texts WHERE key=?',(key,)).fetchone()
    text=row[0] if row else ''
    if not text:
        identifiers=[key]
        if store.db.execute("SELECT 1 FROM sqlite_master WHERE name='game_ocr_echoes'").fetchone():identifiers.extend(row[0] for row in store.db.execute('SELECT remote_key FROM game_ocr_echoes WHERE native_key=?',(key,)))
        for path in source_paths:
            path=Path(path).expanduser()
            if not path.is_file():continue
            try:
                with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)) as source:
                    for identifier in identifiers:
                        if not identifier.startswith(('gsm-line:','gsm:')):continue
                        identifier=identifier.split(':')[-1]
                        value=source.execute('SELECT line_text FROM game_lines WHERE id=?',(identifier,)).fetchone()
                        if value and value[0]:text=value[0];break
            except sqlite3.Error:continue
            if text:break
    if not text and key.startswith('import:') and store.db.execute("SELECT 1 FROM sqlite_master WHERE name='asset_rows'").fetchone():
        asset=store.db.execute('SELECT i.path FROM asset_rows a JOIN import_assets i ON i.id=a.asset WHERE a.key=? LIMIT 1',(key,)).fetchone()
        if asset:
            try:
                path=Path(asset[0]);index=int(key.rsplit(':',1)[-1])
                if path.is_file() and path.stat().st_size<=32*1024*1024:
                    content=path.read_text(encoding='utf-8-sig')
                    if path.suffix.lower()=='.csv':rows=list(csv.DictReader(io.StringIO(content)))
                    elif path.suffix.lower()=='.json':
                        rows=json.loads(content)
                        if isinstance(rows,dict):rows=rows.get('logs',rows.get('data',rows.get('readings',[])))
                    else:rows=[line for line in content.splitlines() if line.strip()]
                    record=rows[index]
                    if isinstance(record,str):text=record
                    elif isinstance(record,dict):
                        record={str(k).strip().lower().replace(' ','_'):v for k,v in record.items()};text=record.get('text') or record.get('sentence') or ''
            except (OSError,ValueError,IndexError,TypeError):pass
    text=str(text)
    if text:
        with store.db:store.db.execute('INSERT OR REPLACE INTO reading_texts VALUES (?,?)',(key,text))
    return dict(text=text[:200000],truncated=len(text)>200000,available=bool(text))
