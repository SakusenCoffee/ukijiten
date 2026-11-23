"""Review events and study-goal activity; never infer reading time or characters."""
from datetime import datetime,date
import hashlib
import json
from pathlib import Path
import time
import urllib.request
from urllib.error import HTTPError,URLError


def jpdb_records(data):
    if not isinstance(data,dict):raise ValueError('Choose jpdb’s Export vocabulary reviews (.json) file.')
    rows=[]
    for group,cards in data.items():
        if not group.startswith('cards_') or not isinstance(cards,list):continue
        for card in cards:
            if not isinstance(card,dict):continue
            identity=str(card.get('vid',card.get('kid',card.get('spelling',''))))+':'+str(card.get('reading',''))
            occurrences={}
            for review in card.get('reviews',[]):
                stamp=float(review['timestamp']);stamp=stamp/1000 if stamp>1e11 else stamp
                day=datetime.fromtimestamp(stamp).astimezone().date().isoformat()
                raw=f'{group}:{identity}:{stamp}:{review.get("grade","")}'
                occurrence=occurrences.get(raw,0);occurrences[raw]=occurrence+1
                key='jpdb:'+hashlib.sha256((raw+':'+str(occurrence)).encode()).hexdigest()
                rows.append((key,'jpdb',day,1,None,stamp,int(bool(review.get('from_anki',False)))))
    if not rows:raise ValueError('This file has no jpdb review events.')
    return rows


def renshuu_records(data):
    heatmap=data.get('heatmap',data) if isinstance(data,dict) else None
    if not isinstance(heatmap,dict):raise ValueError('Choose a Renshuu /heatmap API JSON response.')
    rows=[]
    for week,days in heatmap.items():
        if not isinstance(days,dict):continue
        for raw,value in days.items():
            if value=='scheduled holiday':continue
            if type(value) not in (int,float) or not 0<=value<=100:continue
            try:day=(date.fromisoformat(raw) if '-' in raw else datetime.strptime(raw,'%m/%d/%y').date()).isoformat()
            except ValueError:raise ValueError('Invalid Renshuu activity date.') from None
            rows.append(('renshuu:'+day,'renshuu',day,0,float(value),0,0))
    if not rows:raise ValueError('This response has no Renshuu study-goal activity.')
    return rows


def project_study(store,keys):
    for key in keys:
        candidates=store.db.execute('SELECT payload,updated FROM study_asset_rows WHERE key=? ORDER BY updated DESC',(key,)).fetchall()
        if candidates:store.db.execute('INSERT OR REPLACE INTO study_activity VALUES (?,?,?,?,?,?,?)',json.loads(candidates[0][0]))
        else:store.db.execute('DELETE FROM study_activity WHERE key=?',(key,))


def ingest_study(store,identifier,name,path,kind,data):
    from import_assets import initialize
    initialize(store)
    rows=jpdb_records(data) if kind=='jpdb' else renshuu_records(data)
    keys={row[0] for row in rows}|{row[0] for row in store.db.execute('SELECT key FROM study_asset_rows WHERE asset=?',(identifier,))}
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO import_assets VALUES (?,?,?,?)',(identifier,name,str(path),kind))
        store.db.execute('DELETE FROM study_asset_rows WHERE asset=?',(identifier,))
        store.db.executemany('INSERT INTO study_asset_rows VALUES (?,?,?,?)',[(identifier,row[0],json.dumps(row),time.time()) for row in rows])
        project_study(store,keys)
    return len(rows)


def import_study_file(store,path,kind):
    path=Path(path).expanduser().resolve()
    if path.stat().st_size>128*1024*1024:raise ValueError('The study export exceeds 128 MB.')
    return ingest_study(store,kind+':'+str(path),path.name,path,kind,json.loads(path.read_text(encoding='utf-8-sig')))


def fetch_renshuu(key):
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ValueError('Renshuu redirected the request; the API key was not forwarded.')
    if not key:raise ValueError('Enter your Renshuu API key from its Settings page.')
    request=urllib.request.Request('https://api.renshuu.org/v1/heatmap',headers={'Authorization':'Bearer '+key,'Accept':'application/json'})
    try:
        with urllib.request.build_opener(Redirect()).open(request,timeout=20) as response:raw=response.read(16*1024*1024+1)
    except HTTPError as error:raise ValueError('Check the Renshuu API key.' if error.code in (401,403) else f'Renshuu returned HTTP {error.code}.') from None
    except (URLError,TimeoutError,OSError):raise ValueError('Renshuu is unavailable; saved activity was kept.') from None
    if len(raw)>16*1024*1024:raise ValueError('The Renshuu response exceeds the import limit.')
    return json.loads(raw)
