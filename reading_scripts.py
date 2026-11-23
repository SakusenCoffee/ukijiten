"""Cached script counts for entries whose original text is available."""
import unicodedata
from contextlib import closing
from pathlib import Path
import sqlite3


def backfill_gsm_text(store, filename):
    """Recover text for existing UUIDs only; never import additional readings."""
    path=Path(filename).expanduser()
    if store.preference('script_text_backfill_done',False) or not path.is_file():return 0
    keys={key.removeprefix('gsm-line:'):key for (key,) in store.db.execute(
        "SELECT r.key FROM readings r LEFT JOIN reading_texts t USING(key) WHERE r.key LIKE 'gsm-line:%' AND t.key IS NULL")}
    saved=[]
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)) as source:
        identifiers=list(keys)
        for offset in range(0,len(identifiers),500):
            chunk=identifiers[offset:offset+500]
            for identifier,text in source.execute('SELECT id,line_text FROM game_lines WHERE id IN ('+','.join('?' for _ in chunk)+')',chunk):
                if text:saved.append((keys[identifier],text))
    with store.db:store.db.executemany('INSERT OR IGNORE INTO reading_texts VALUES (?,?)',saved)
    store.set_preference('script_text_backfill_done',True)
    return len(saved)


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS reading_scripts (
            key TEXT PRIMARY KEY,characters INTEGER,kanji INTEGER,hiragana INTEGER,katakana INTEGER);
        CREATE TRIGGER IF NOT EXISTS scripts_text_insert AFTER INSERT ON reading_texts
        BEGIN DELETE FROM reading_scripts WHERE key=NEW.key; END;
        CREATE TRIGGER IF NOT EXISTS scripts_text_update AFTER UPDATE OF text ON reading_texts
        WHEN OLD.text<>NEW.text BEGIN DELETE FROM reading_scripts WHERE key=NEW.key; END;
        CREATE TRIGGER IF NOT EXISTS scripts_text_delete AFTER DELETE ON reading_texts
        BEGIN DELETE FROM reading_scripts WHERE key=OLD.key; END;
    ''')


def totals(db, readings, total):
    from reading_stats import japanese_characters
    missing = db.execute('''SELECT t.key,t.text FROM reading_texts t
        JOIN readings r USING(key) LEFT JOIN reading_scripts s USING(key)
        WHERE s.key IS NULL''').fetchall()
    with db:
        for key,text in missing:
            characters = japanese_characters(text)
            kanji = hiragana = katakana = 0
            for char in characters:
                name = unicodedata.name(char,'')
                if name.startswith('HIRAGANA'):hiragana += 1
                elif name.startswith('KATAKANA') or char=='ー':katakana += 1
                else:kanji += 1
            db.execute('INSERT OR REPLACE INTO reading_scripts VALUES (?,?,?,?,?)',
                       (key,len(characters),kanji,hiragana,katakana))
    counts = db.execute(f'''SELECT COALESCE(SUM(s.kanji),0),COALESCE(SUM(s.hiragana),0),
        COALESCE(SUM(s.katakana),0) FROM {readings} r JOIN reading_scripts s USING(key)
        WHERE r.characters>0 AND r.characters=s.characters''').fetchone()
    return dict(zip(('kanji','hiragana','katakana','unclassified'),(*counts,max(0,total-sum(counts)))))
