"""Reading-aware frequency and pitch metadata from selected dictionary sources."""
import html
import json
import sqlite3
from collections import OrderedDict, defaultdict
from pathlib import Path
from threading import RLock
from time import monotonic
from pitch_accent import hiragana,parse_accents,morae,render_variant


def sources(database):
    rows=database.execute('SELECT id,title,path FROM dictionaries ORDER BY sort_order,id').fetchall()
    columns={row[1] for row in database.execute('PRAGMA table_info(dictionaries)')}
    has_table=database.execute("SELECT 1 FROM sqlite_master WHERE name='term_metadata'").fetchone()
    result=[]
    for did,title,path in rows:
        frequency=pitch=False
        if 'has_frequency' in columns:
            frequency,pitch=map(bool,database.execute('SELECT has_frequency,has_pitch FROM dictionaries WHERE id=?',(did,)).fetchone())
        if has_table and 'has_frequency' not in columns:
            kinds={row[0] for row in database.execute('SELECT DISTINCT mode FROM term_metadata WHERE dictionary_id=?',(did,))}
            frequency|='freq' in kinds;pitch|='pitch' in kinds
        pitch|='nhk' in title.lower()
        kanji=kanji_frequency=False
        if 'has_kanji' in columns:
            kanji,kanji_frequency=map(bool,database.execute('SELECT has_kanji,has_kanji_frequency FROM dictionaries WHERE id=?',(did,)).fetchone())
        result.append(dict(id=did,title=title,path=path,frequency=frequency,pitch=pitch,kanji=kanji,kanji_frequency=kanji_frequency))
    return result


class MetadataResults(list):
    def __init__(self, entries, metadata):
        super().__init__(entries)
        self.metadata = metadata


class MetadataCache:
    """Bounded shared cache; workers own their SQLite connections."""
    def __init__(self, path, limit=4096):
        self.path = Path(path).resolve()
        self.limit = limit
        self.rows = OrderedDict()
        self.lock = RLock()

    def get(self, key):
        with self.lock:
            if key not in self.rows:
                return None
            self.rows.move_to_end(key)
            return self.rows[key]

    def put(self, key, value):
        with self.lock:
            self.rows[key] = value
            self.rows.move_to_end(key)
            while len(self.rows) > self.limit:
                self.rows.popitem(last=False)

    def enrich(self, entries, selection, cancelled):
        if not entries or cancelled.is_set() or not any(selection):
            return MetadataResults(entries, {})
        database = sqlite3.connect(f'{self.path.as_uri()}?mode=ro', uri=True, timeout=1)
        try:
            deadline = monotonic() + 3
            database.set_progress_handler(lambda: cancelled.is_set() or monotonic() > deadline, 1000)
            # Catalog revisions and their data must come from the same snapshot.
            database.execute('BEGIN')
            metadata = selected_rows(database, entries, *selection, cache=self, cancelled=cancelled)
            return MetadataResults(entries, metadata)
        finally:
            database.close()


def selected_rows(database,entries,frequency_paths,pitch_paths,cache=None,cancelled=None):
    keys=list(dict.fromkeys((row[0],row[1]) for row in entries))
    if not keys or not(frequency_paths or pitch_paths):return dict.fromkeys(keys,'')
    selected_freq=set(frequency_paths);selected_pitch=set(pitch_paths)
    dictionaries=[row for row in database.execute('SELECT id,title,path,stamp FROM dictionaries ORDER BY sort_order,id')
                  if row[2] in selected_freq or row[2] in selected_pitch]
    # Source revisions, selection and ordering invalidate cached values automatically.
    signature=(tuple(frequency_paths),tuple(pitch_paths),tuple((did,title,path,stamp) for did,title,path,stamp in dictionaries))
    output={};missing=[]
    for key in keys:
        cached=cache.get((signature,*key)) if cache is not None else None
        if cached is None:missing.append(key)
        else:output[key]=cached
    if not missing:return output
    if not dictionaries:return dict.fromkeys(keys,'')
    if cancelled is not None and cancelled.is_set():return output
    metadata=defaultdict(list);legacy=defaultdict(list)
    terms=list(dict.fromkeys(term for term,_ in missing))
    ids=[row[0] for row in dictionaries];pitch_ids=[row[0] for row in dictionaries if row[2] in selected_pitch]
    has_meta=database.execute("SELECT 1 FROM sqlite_master WHERE name='term_metadata'").fetchone()
    for start in range(0,len(terms),256):
        if cancelled is not None and cancelled.is_set():return output
        batch=terms[start:start+256];slots=','.join('?' for _ in batch)
        if has_meta:
            source_slots=','.join('?' for _ in ids)
            for term,did,mode,raw in database.execute(f'SELECT term,dictionary_id,mode,data FROM term_metadata INDEXED BY term_metadata_lookup WHERE term IN ({slots}) AND dictionary_id IN ({source_slots})',(*batch,*ids)):
                metadata[(did,term)].append((mode,raw))
        if pitch_ids:
            source_slots=','.join('?' for _ in pitch_ids)
            # Without this hint SQLite may choose entries_dictionary and scan every
            # entry of a pitch source. Exact headword probes already have an index.
            for term,did,reading,glossary in database.execute(f'SELECT term,dictionary_id,reading,glossary FROM entries INDEXED BY entries_term WHERE term IN ({slots}) AND dictionary_id IN ({source_slots})',(*batch,*pitch_ids)):
                legacy[(did,term)].append((reading,glossary))
    for term,reading in missing:
        if cancelled is not None and cancelled.is_set():return output
        key=(term,reading)
        frequency_html={};pitch_html={}
        for did,title,path,_ in dictionaries:
            use_freq=path in selected_freq;use_pitch=path in selected_pitch
            if not(use_freq or use_pitch):continue
            label=html.escape(title)
            frequencies=[];pitches=[]
            if has_meta:
                for mode,raw in metadata[(did,term)]:
                    try:data=json.loads(raw)
                    except (ValueError,TypeError):continue
                    source_reading=data.get('reading') if isinstance(data,dict) else None
                    if source_reading is not None and not isinstance(source_reading,str):continue
                    if source_reading and reading and hiragana(source_reading or term)!=hiragana(reading):continue
                    if mode=='freq' and use_freq:
                        value=data.get('frequency',data) if isinstance(data,dict) else data
                        if isinstance(value,dict):value=value.get('displayValue') or value.get('value')
                        if isinstance(value,(int,float,str)) and not isinstance(value,bool):
                            text=str(value)
                            if text not in frequencies:frequencies.append(text)
                    if mode=='pitch' and use_pitch and isinstance(data,dict):
                        parts=morae(source_reading or reading or term)
                        variants=data.get('pitches',[])
                        if not isinstance(variants,list):continue
                        for pitch in variants:
                            position=pitch.get('position') if isinstance(pitch,dict) else None
                            variant=(tuple(parts),position)
                            if type(position)is int and 0<=position<=len(parts) and variant not in pitches:pitches.append(variant)
            if use_pitch:
                for source_reading,glossary in legacy[(did,term)]:
                    if reading and hiragana(source_reading or term)!=hiragana(reading):continue
                    try:
                        for variant in parse_accents(glossary):
                            if variant not in pitches:pitches.append(variant)
                    except (ValueError,TypeError):continue
            if frequencies:frequency_html[path]=('<div class="frequency-source"><span class="metadata-source">'+label+'</span>'+''.join('<span class="frequency-value">'+html.escape(value)+'</span>' for value in frequencies)+'</div>')
            if pitches:pitch_html[path]=('<div class="pitch-source" aria-label="'+label+' pitch accent"><span class="pitch-badge">'+label+'</span>'+''.join(render_variant(*variant) for variant in pitches)+'</div>')
        output[key]=''
        frequency_sources=''.join(frequency_html.get(path,'') for path in frequency_paths)
        if frequency_sources:output[key]+='<div class="frequency-row">'+frequency_sources+'</div>'
        pitch_sources=''.join(pitch_html.get(path,'') for path in pitch_paths)
        if pitch_sources:output[key]+='<div class="pitch-row">'+pitch_sources+'</div>'
        if cache is not None:cache.put((signature,*key),output[key])
    return output
