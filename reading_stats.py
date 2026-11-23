"""Local reading ledger. Source files and GSM's database are never modified."""
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import sqlite3
import unicodedata
import uuid
from study_day import study_date,validate_cutoff


def gsm_line_key(identifier, session=''):
    try:
        return 'gsm-line:' + str(uuid.UUID(str(identifier)))
    except ValueError:
        return 'gsm:' + str(session) + ':' + str(identifier)


def japanese_characters(text):
    letters = ''.join(c for c in str(text) if (unicodedata.category(c).startswith('L') or c == '〇') and (
        '\u3040' <= c <= '\u30ff' or '\uff66' <= c <= '\uff9f' or '\u3400' <= c <= '\u4dbf' or
        '\u4e00' <= c <= '\u9fff' or '\uf900' <= c <= '\ufaff' or
        '\U00020000' <= c <= '\U000323af' or c in '々〆〇'))
    return unicodedata.normalize('NFKC', letters)


def local_timestamp(value=None):
    if value:
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return dt.astimezone() if dt.tzinfo else dt.astimezone()
        except ValueError:
            raise ValueError('Invalid reading date: ' + str(value))
    return datetime.now().astimezone()


def ocr_text_digest(text):
    return hashlib.sha256(''.join(unicodedata.normalize('NFKC',str(text)).split()).encode()).hexdigest()


class ReadingStats:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS readings (
                key TEXT PRIMARY KEY, day TEXT NOT NULL, source TEXT NOT NULL,
                characters INTEGER NOT NULL, seconds REAL NOT NULL DEFAULT 0,
                kind TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                captured REAL NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS readings_day ON readings(day);
            CREATE INDEX IF NOT EXISTS readings_source ON readings(source);
            CREATE INDEX IF NOT EXISTS readings_live_time ON readings(kind,source,day,captured);
            CREATE INDEX IF NOT EXISTS readings_capture_clock ON readings(kind,source,captured);
            CREATE TABLE IF NOT EXISTS reading_texts(key TEXT PRIMARY KEY,text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reading_deleted(key TEXT PRIMARY KEY,deleted REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS anki_reviews (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL, deck TEXT NOT NULL,
                milliseconds INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS anki_daily (
                day TEXT PRIMARY KEY,milliseconds INTEGER NOT NULL,reviews INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS anki_deck_totals (
                deck TEXT PRIMARY KEY,milliseconds INTEGER NOT NULL,reviews INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS imports (digest TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS study_activity(key TEXT PRIMARY KEY,service TEXT,day TEXT,reviews INTEGER,completion REAL,captured REAL,from_anki INTEGER);
            CREATE TABLE IF NOT EXISTS study_asset_rows(asset TEXT,key TEXT,payload TEXT,updated REAL,PRIMARY KEY(asset,key));
            CREATE INDEX IF NOT EXISTS study_asset_key ON study_asset_rows(key);
            CREATE TABLE IF NOT EXISTS game_ocr_texts(key TEXT PRIMARY KEY,digest TEXT,captured REAL);
            CREATE INDEX IF NOT EXISTS game_ocr_digest ON game_ocr_texts(digest,captured);
            CREATE TABLE IF NOT EXISTS game_ocr_echoes(remote_key TEXT PRIMARY KEY,native_key TEXT,digest TEXT);
            CREATE TABLE IF NOT EXISTS gsm_live_texts(key TEXT PRIMARY KEY,digest TEXT,captured REAL);
            CREATE INDEX IF NOT EXISTS gsm_live_digest ON gsm_live_texts(digest,captured);
        ''')
        self.last_plain = None
        from reading_scripts import initialize
        initialize(self.db)
        self.v2 = False
        self.batching = False
        # GSM persists these same UUIDs in game_lines; share identity across history/live feeds.
        with self.db:
            for row in self.db.execute("SELECT * FROM readings WHERE key LIKE 'gsm:%'").fetchall():
                key = gsm_line_key(row[0].rsplit(':', 1)[-1])
                if not key.startswith('gsm-line:'):
                    continue
                existing = self.db.execute('SELECT revision FROM readings WHERE key=?', (key,)).fetchone()
                if not existing or existing[0] <= row[6]:
                    self.db.execute('INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?,?)', (key, *row[1:]))
                self.db.execute('DELETE FROM readings WHERE key=?', (row[0],))

    def preference(self, key, default):
        row = self.db.execute('SELECT value FROM preferences WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_preference(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)', (key, json.dumps(value)))

    def record(self, key, text, source='Texthooker', timestamp=None, revision=0, excluded=False):
        if self.db.execute('SELECT 1 FROM reading_deleted WHERE key=?',(key,)).fetchone():return False
        stamp = local_timestamp(timestamp)
        if key.startswith(('gsm','plain:')):
            digest=ocr_text_digest(text)
            native=self.db.execute('SELECT t.key FROM game_ocr_texts t JOIN readings r ON r.key=t.key WHERE digest=? AND ABS(t.captured-?)<120 ORDER BY ABS(t.captured-?) LIMIT 1',(digest,stamp.timestamp(),stamp.timestamp())).fetchone()
            linked=self.db.execute('SELECT native_key FROM game_ocr_echoes e JOIN readings r ON r.key=e.native_key WHERE remote_key=? AND digest=?',(key,digest)).fetchone()
            if native or linked:
                self.db.execute('INSERT OR REPLACE INTO reading_texts VALUES (?,?)',((native or linked)[0],str(text)))
                self.db.execute('INSERT OR REPLACE INTO game_ocr_echoes VALUES (?,?,?)',(key,(native or linked)[0],digest))
                self.db.execute('DELETE FROM readings WHERE key=?',(key,))
                if not self.batching:self.db.commit()
                return False
            self.db.execute('INSERT OR REPLACE INTO gsm_live_texts VALUES (?,?,?)',(key,digest,stamp.timestamp()))
        chars = len(japanese_characters(text)) if not excluded else 0
        old = self.db.execute('SELECT revision,seconds,characters,source,day FROM readings WHERE key=?', (key,)).fetchone()
        if old and revision < old[0]:
            return False
        if old and (revision, chars, source, stamp.date().isoformat()) == (old[0], old[2], old[3], old[4]):
            self.db.execute('INSERT INTO reading_texts VALUES (?,?) ON CONFLICT(key) DO UPDATE SET text=excluded.text WHERE reading_texts.text<>excluded.text',(key,str(text)))
            if not self.batching:self.db.commit()
            return False
        seconds = old[1] if old else 0
        if not old and chars:
            previous = self.db.execute("SELECT MAX(captured) FROM readings WHERE kind='live' AND source=? AND captured<=?", (source, stamp.timestamp())).fetchone()[0]
            cutoff=self.day_cutoff_hour()
            if previous is not None and 0 < stamp.timestamp()-previous <= 90 and study_date(datetime.fromtimestamp(previous).astimezone(),cutoff)==study_date(stamp,cutoff):
                seconds=stamp.timestamp()-previous
        self.db.execute('INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?,?)',
            (key, stamp.date().isoformat(), source, chars, seconds if chars else 0, 'live', revision, stamp.timestamp()))
        self.db.execute('INSERT OR REPLACE INTO reading_texts VALUES (?,?)',(key,str(text)))
        if not self.batching:
            self.db.commit()
        return True

    def ingest(self, message):
        try:
            event = json.loads(message)
        except (ValueError, TypeError):
            event = None
        if isinstance(event, dict) and not event.get('event') and isinstance(event.get('text') or event.get('sentence'),str):
            self.ingest(event.get('text') or event['sentence'])
            return
        if isinstance(event,str):
            self.ingest(event)
            return
        if isinstance(event, dict):
            kind = event.get('event', '')
            if kind == 'text_v2_snapshot':
                self.v2 = True
                with self.db:
                    self.batching = True
                    try:
                        for row in event.get('lines', []):
                            self.ingest(json.dumps({'event': 'text_v2_append', 'data': row}))
                    finally:
                        self.batching = False
                return
            if kind.startswith('text_v2_'):
                self.v2 = True
                if kind == 'text_v2_reset':
                    return
            elif self.v2 or kind not in ('text_received', 'text_updated'):
                return
            row = event.get('data')
            if not isinstance(row, dict) or 'text' not in row:
                return
            identifier = row.get('id') or row.get('line_id')
            if identifier is None:
                return
            self.record(gsm_line_key(identifier, row.get('session_id', '')),
                row['text'], str(row.get('scene') or row.get('source_display_name') or 'GSM'),
                row.get('captured_at') or row.get('time'), int(row.get('revision', 0)),
                bool(row.get('excluded_from_stats') or row.get('relay_only')))
        elif event is None and message.strip():
            # Plain-text legacy feeds have no IDs; suppress immediate repeated frames only.
            if message == self.last_plain:
                return
            self.last_plain = message
            self.record('plain:' + str(datetime.now(timezone.utc).timestamp()), message)

    def import_file(self, path):
        path = Path(path)
        with path.open('rb') as source:
            digest = hashlib.file_digest(source,'sha256').hexdigest()
        if self.db.execute('SELECT 1 FROM imports WHERE digest=?', (digest,)).fetchone():
            return 0
        if path.suffix.lower() == '.zip':
            from reading_exports import ttsu_zip_records
            rows=ttsu_zip_records(path)
        else:
            text=path.read_text(encoding='utf-8-sig')
        if path.suffix.lower() == '.zip':
            pass
        elif path.suffix.lower() == '.csv':
            rows = list(csv.DictReader(io.StringIO(text)))
        elif path.suffix.lower() == '.json':
            rows = json.loads(text)
            if isinstance(rows, dict):
                rows = rows.get('logs', rows.get('data', rows.get('readings')))
            if not isinstance(rows, list):
                raise ValueError('JSON must contain a list of reading records.')
        else:
            rows = [{'text': line} for line in text.splitlines() if line.strip()]
        records = [];texts=[]
        for index, row in enumerate(rows):
            if isinstance(row, str):
                row = {'text': row}
            if not isinstance(row, dict):
                raise ValueError('Each reading record must be text or an object.')
            row = {str(k).strip().lower().replace(' ', '_'): v for k, v in row.items()}
            language = str(row.get('language', 'Japanese')).lower()
            if language not in ('japanese', 'ja', 'jp', '日本語', ''):
                continue
            if 'datekey' in row and 'readingtime' in row:
                row['date']=row['datekey']
                row['characters']=row.get('charactersread',0)
                row['duration_minutes']=float(row['readingtime'])/60
                row['source']='Ttsu · '+str(row.get('title') or path.stem)
                row['_ttsu']=True
            stamp = local_timestamp(row.get('date') or row.get('time') or row.get('timestamp'))
            source = str(row.get('source') or row.get('log_name') or row.get('title') or path.stem)
            if 'text' in row or 'sentence' in row:
                chars = len(japanese_characters(row.get('text', row.get('sentence', ''))))
            elif 'characters' in row:
                chars = int(str(row['characters']).replace(',', '') or 0)
            else:
                raise ValueError('Records need a Text or Characters column.')
            seconds = float(row.get('duration_minutes', row.get('duration', 0)) or 0) * 60
            if chars < 0 or not math.isfinite(seconds) or seconds < 0 or seconds > 31536000:
                raise ValueError('Character counts and duration must be valid positive numbers.')
            if chars or seconds:
                key='ttsu:'+hashlib.sha256(json.dumps([source,stamp.date().isoformat()]).encode()).hexdigest() if row.get('_ttsu') else f'import:{digest}:{index}'
                records.append((key, stamp.date().isoformat(), source, chars, seconds, 'import', 0, stamp.timestamp()))
                if row.get('text') or row.get('sentence'):texts.append((key,str(row.get('text') or row['sentence'])))
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO readings SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM reading_deleted WHERE key=?)', [(*row,row[0]) for row in records])
            self.db.executemany('INSERT OR REPLACE INTO reading_texts SELECT ?,? WHERE EXISTS(SELECT 1 FROM readings WHERE key=?)',[(*row,row[0]) for row in texts])
            self.db.execute('INSERT INTO imports VALUES (?)', (digest,))
        return len(records)

    def add_manual_entry(self, characters, hours, minutes, description, day=None, identifier=None):
        values = (characters, hours, minutes)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError('Enter nonnegative whole numbers.')
        if characters > 1000000000 or hours > 1000000 or minutes > 59:
            raise ValueError('Minutes must be 0–59; characters or hours exceed the limit.')
        seconds = hours * 3600 + minutes * 60
        if not characters and not seconds:
            raise ValueError('Enter characters or reading time.')
        if not isinstance(description, str) or len(description.strip()) > 500:
            raise ValueError('Description must be 500 characters or fewer.')
        if identifier is not None and not isinstance(identifier, str):
            raise ValueError('Invalid entry identifier.')
        entry_day = date.fromisoformat(day) if day else study_date(cutoff=self.day_cutoff_hour())
        key = 'manual:' + str(uuid.UUID(identifier) if identifier else uuid.uuid4())
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?,?,?)',
                (key, entry_day.isoformat(), description.strip() or 'Manual reading', characters,
                 seconds, 'manual', 0, datetime.now().timestamp()))
        return key

    def day_cutoff_hour(self):
        try:return validate_cutoff(self.preference('day_cutoff_hour',0))
        except ValueError:return 0

    def summary(self):
        cutoff=self.day_cutoff_hour()
        today=study_date(cutoff=cutoff)
        # Keep the original dates and timestamps intact. Only the reporting view
        # changes, so the cutoff is reversible and cannot duplicate history.
        readings='readings'
        metrics=self.preference('source_metrics',{})
        mask=any(not options.get(field,True) for kind,options in metrics.items() if kind in ('gsm','game_ocr','mokuro','mokuro_browser','files','ttsu') for field in ('include_time','include_characters'))
        day_sql=f"CASE WHEN kind='live' AND captured>0 THEN date(captured,'unixepoch','localtime','-{cutoff} hours') ELSE day END" if cutoff else 'day'
        if mask:
            assets=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='asset_rows'").fetchone()
            owner="COALESCE((SELECT i.kind FROM asset_rows a JOIN import_assets i ON i.id=a.asset WHERE a.key=r.key ORDER BY a.rank DESC LIMIT 1),'files')" if assets else "'files'"
            origin=f"CASE WHEN key LIKE 'manual:%' THEN 'manual' WHEN key LIKE 'game-ocr:%' THEN 'game_ocr' WHEN key LIKE 'manga:%' THEN 'mokuro' WHEN key LIKE 'mokuro-browser:%' THEN 'mokuro_browser' WHEN key LIKE 'gsm%' OR key LIKE 'plain:%' THEN 'gsm' WHEN source LIKE 'Ttsu · %' THEN 'ttsu' ELSE {owner} END"
            flags=lambda field:'CASE origin '+''.join("WHEN '"+kind+"' THEN "+str(int(options.get(field,True)))+' ' for kind,options in metrics.items() if kind in ('gsm','game_ocr','mokuro','mokuro_browser','files','ttsu'))+'ELSE 1 END'
            readings=f"(SELECT key,{day_sql} AS day,source,characters*({flags('include_characters')}) AS characters,seconds*({flags('include_time')}) AS seconds,kind,revision,captured FROM (SELECT r.*,{origin} AS origin FROM readings r))"
        elif cutoff:readings=f"(SELECT key,{day_sql} AS day,source,characters,seconds,kind,revision,captured FROM readings)"
        rows = self.db.execute(f'SELECT day,SUM(characters),SUM(seconds) FROM {readings} WHERE characters>0 OR seconds>0 GROUP BY day ORDER BY day').fetchall()
        days = {day: {'characters': chars, 'seconds': seconds} for day, chars, seconds in rows}
        reading_seconds = sum(row[2] for row in rows)
        anki_decks = [dict(zip(('deck','seconds','reviews'), row)) for row in self.db.execute(
            'SELECT deck,milliseconds/1000.0,reviews FROM anki_deck_totals ORDER BY deck')]
        anki_seconds = sum(deck['seconds'] for deck in anki_decks)
        include_anki_time=metrics.get('anki',{}).get('include_time',True)
        if not include_anki_time:
            anki_seconds=0
            for deck in anki_decks:deck['seconds']=0
        if cutoff and self.db.execute('SELECT 1 FROM anki_reviews LIMIT 1').fetchone():
            anki_rows=self.db.execute(f"SELECT date(id/1000.0,'unixepoch','localtime','-{cutoff} hours'),SUM(milliseconds),COUNT(*) FROM anki_reviews GROUP BY 1").fetchall()
        else:
            anki_rows=self.db.execute('SELECT day,milliseconds,reviews FROM anki_daily').fetchall()
        if not include_anki_time:anki_rows=[(day,0,reviews) for day,_,reviews in anki_rows]
        for day,milliseconds,_ in anki_rows:
            days.setdefault(day, {'characters': 0, 'seconds': 0})['seconds'] += milliseconds/1000
        consistency_days={day:{'characters':characters,'seconds':seconds} for day,characters,seconds in rows}
        anki_days={day:{'seconds':milliseconds/1000,'reviews':reviews} for day,milliseconds,reviews in anki_rows}
        total = sum(row[1] for row in rows)
        activity_dates = {row[0] for row in rows} | {day for day,value in anki_days.items() if value['reviews']>0 or value['seconds']>0}
        study_sources={}
        for service in ('jpdb','renshuu'):
            if not metrics.get(service,{}).get('include_activity',True):continue
            condition=" AND from_anki=0" if service=='jpdb' and not metrics.get(service,{}).get('include_anki_reviews',False) else ''
            source_day=f"CASE WHEN captured>0 THEN date(captured,'unixepoch','localtime','-{cutoff} hours') ELSE day END" if cutoff else 'day'
            records=self.db.execute(f'SELECT {source_day},SUM(reviews),MAX(completion) FROM study_activity WHERE service=?{condition} GROUP BY 1 ORDER BY 1',(service,)).fetchall()
            if records:
                study_sources[service]={'reviews':sum(row[1] for row in records),'days':{day:{'reviews':reviews,'completion':completion} for day,reviews,completion in records}}
                activity_dates.update(day for day,reviews,completion in records if reviews>0 or (completion or 0)>0)
        active = sorted(date.fromisoformat(day) for day in activity_dates if day <= today.isoformat())
        longest = streak = 0
        previous = None
        for day in active:
            streak = streak + 1 if previous and day == previous + timedelta(days=1) else 1
            longest = max(longest, streak)
            previous = day
        current = 0
        reading_dates = activity_dates
        day = today if today.isoformat() in reading_dates else today - timedelta(days=1)
        while day.isoformat() in reading_dates:
            current += 1
            day -= timedelta(days=1)
        aliases = self.preference('source_aliases', {})
        parameters = []
        display_source = 'source'
        if aliases:
            display_source = 'CASE source ' + ' '.join('WHEN ? THEN ?' for _ in aliases) + ' ELSE source END'
            parameters = [value for pair in aliases.items() for value in pair]
        sources = [dict(zip(('source', 'characters', 'seconds', 'days'), row)) for row in self.db.execute(
            f'SELECT {display_source} AS display_source,SUM(characters),SUM(seconds),COUNT(DISTINCT day) FROM {readings} WHERE characters>0 OR seconds>0 GROUP BY display_source ORDER BY SUM(characters) DESC', parameters)]
        from reading_scripts import totals as script_totals
        return {'scripts':script_totals(self.db,readings,total),'study_sources':study_sources,'today_day':today.isoformat(),'day_cutoff_hour':cutoff,'total': total, 'today': days.get(today.isoformat(), {}).get('characters', 0),
            'days': days, 'consistency_days': consistency_days, 'anki_days': anki_days, 'active_days': len(rows), 'streak': current, 'longest': longest,
            'seconds': reading_seconds + anki_seconds, 'reading_seconds': reading_seconds, 'anki_seconds': anki_seconds, 'anki_decks': anki_decks, 'sources': sources,
            'recent': [dict(zip(('day','source','characters','kind','seconds'), row)) for row in self.db.execute(
                f'SELECT day,{display_source} AS display_source,SUM(characters),kind,SUM(seconds) FROM {readings} WHERE characters>0 OR seconds>0 GROUP BY day,display_source,kind ORDER BY day DESC LIMIT 12', parameters)],
            'capture': self.preference('capture', True)}
