"""Dictionary storage and schema initialization, independent of the UI."""
from pathlib import Path
import sqlite3

APP_DIR = Path.home() / '.local/share/yomitan-goldendict'
DB_PATH = APP_DIR / 'dictionaries.sqlite3'

def connect_database(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS dictionaries (id INTEGER PRIMARY KEY, path TEXT UNIQUE, title TEXT, stamp TEXT, count INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS entries (dictionary_id INTEGER, term TEXT, reading TEXT, glossary TEXT)')
    columns = {row[1] for row in db.execute('PRAGMA table_info(dictionaries)')}
    if 'enabled' not in columns:
        db.execute('ALTER TABLE dictionaries ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1')
    if 'sort_order' not in columns:
        db.execute('ALTER TABLE dictionaries ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0')
        db.execute('UPDATE dictionaries SET sort_order=id')
    db.execute('CREATE TABLE IF NOT EXISTS term_metadata (dictionary_id INTEGER,term TEXT,mode TEXT,data TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS term_metadata_lookup ON term_metadata(term,dictionary_id,mode)')
    for column in ('has_frequency','has_pitch'):
        if column not in columns:db.execute(f'ALTER TABLE dictionaries ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0')
    for column in ('has_kanji','has_kanji_frequency'):
        if column not in columns:db.execute(f'ALTER TABLE dictionaries ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0')
    db.execute('CREATE TABLE IF NOT EXISTS kanji_entries (dictionary_id INTEGER,character TEXT,onyomi TEXT,kunyomi TEXT,tags TEXT,meanings TEXT,stats TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS kanji_entries_lookup ON kanji_entries(character,dictionary_id)')
    db.execute('CREATE TABLE IF NOT EXISTS kanji_metadata (dictionary_id INTEGER,character TEXT,mode TEXT,data TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS kanji_metadata_lookup ON kanji_metadata(character,dictionary_id,mode)')
    db.execute('CREATE TABLE IF NOT EXISTS dictionary_tags (dictionary_id INTEGER,name TEXT,notes TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS dictionary_tags_lookup ON dictionary_tags(dictionary_id,name)')
    db.execute("UPDATE dictionaries SET has_pitch=1 WHERE lower(title) LIKE '%nhk%' AND has_pitch=0")
    db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    if db.execute('SELECT 1 FROM dictionaries LIMIT 1').fetchone():
        db.execute("INSERT OR IGNORE INTO settings VALUES('initialized','1')")
    db.execute('CREATE INDEX IF NOT EXISTS entries_term ON entries(term)')
    db.execute('CREATE INDEX IF NOT EXISTS entries_reading ON entries(reading)')
    db.execute('CREATE INDEX IF NOT EXISTS entries_dictionary ON entries(dictionary_id)')
    db.commit()
    return db


