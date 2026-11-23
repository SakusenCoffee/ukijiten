"""Exact, indexed kanji/hanzi pages and clickable Unicode headwords."""
import html
import json
import sqlite3
import unicodedata
from threading import Event
from time import monotonic
from urllib.parse import quote

from async_lookup import AsyncLookup
from yomitan_goldendict import render


def is_character(value):
    if len(value) != 1:
        return False
    return value == '〇' or unicodedata.name(value, '').startswith(
        ('CJK UNIFIED IDEOGRAPH-', 'CJK COMPATIBILITY IDEOGRAPH-'))


def headword_markup(term):
    parts = []
    for char in term:
        if is_character(char):
            escaped = html.escape(char)
            parts.append(f'<a class="headword-character" data-character="{escaped}" href="?kanji={quote(char)}" aria-label="Look up {escaped}">{escaped}</a>')
        else:
            parts.append(html.escape(char))
    return ''.join(parts)


def frequency_value(data):
    if isinstance(data, dict):
        data = data.get('frequency', data)
    if isinstance(data, dict):
        display = data.get('displayValue')
        data = display if display is not None else data.get('value')
    return str(data) if isinstance(data, (str, int, float)) and not isinstance(data, bool) else None


def lookup_character(character, cancelled, path, enabled_ids=None):
    if not is_character(character) or cancelled.is_set():
        return ''
    db = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=1)
    deadline = monotonic() + 3
    try:
        db.set_progress_handler(lambda: cancelled.is_set() or monotonic() > deadline, 1000)
        db.execute('BEGIN')
        condition = 'd.enabled=1' if enabled_ids is None else 'd.id IN (' + ','.join('?' for _ in enabled_ids) + ')'
        args = (character, *(enabled_ids or []))
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        chunks = ['<section class="character-page"><h2 class="character-headword">' + html.escape(character) + '</h2>']
        if 'kanji_metadata' in tables:
            frequencies = []
            for title, raw in db.execute(f'''SELECT d.title,k.data FROM kanji_metadata k
                JOIN dictionaries d ON d.id=k.dictionary_id
                WHERE k.character=? AND k.mode='freq' AND {condition}
                ORDER BY d.sort_order,d.id,k.rowid''', args):
                try:
                    value = frequency_value(json.loads(raw))
                except (ValueError, TypeError):
                    continue
                if value is not None:
                    frequencies.append('<div class="frequency-source"><span class="metadata-source">' + html.escape(title) + '</span><span class="frequency-value">' + html.escape(value) + '</span></div>')
            if frequencies:
                chunks.append('<div class="frequency-row">' + ''.join(frequencies) + '</div>')
        count = 0
        if 'kanji_entries' in tables:
            rows = db.execute(f'''SELECT k.dictionary_id,d.title,k.onyomi,k.kunyomi,k.tags,k.meanings,k.stats
                FROM kanji_entries k JOIN dictionaries d ON d.id=k.dictionary_id
                WHERE k.character=? AND {condition} ORDER BY d.sort_order,d.id,k.rowid''', args)
            for did, title, on, kun, tags, raw_meanings, raw_stats in rows:
                if cancelled.is_set():
                    return ''
                chunks.append('<article class="kanji-entry"><small>' + html.escape(title) + '</small>')
                readings = [html.escape(value) for value in (on, kun) if value]
                if readings:
                    chunks.append('<div class="reading kanji-readings">' + ' · '.join(readings) + '</div>')
                if tags:
                    chunks.append('<div class="kanji-tags">' + html.escape(tags) + '</div>')
                meanings, stats = json.loads(raw_meanings), json.loads(raw_stats)
                chunks.append('<div class="definition">')
                if isinstance(meanings, list):
                    chunks.append('<ul>' + ''.join('<li>' + render(item) + '</li>' for item in meanings if item) + '</ul>')
                else:
                    chunks.append(render(meanings))
                chunks.append('</div>')
                if isinstance(stats, dict) and stats:
                    notes = dict(db.execute('SELECT name,notes FROM dictionary_tags WHERE dictionary_id=?', (did,))) if 'dictionary_tags' in tables else {}
                    chunks.append('<dl class="kanji-stats">' + ''.join('<div><dt>' + html.escape(notes.get(key) or key) + '</dt><dd>' + html.escape(str(value)) + '</dd></div>' for key, value in stats.items()) + '</dl>')
                chunks.append('</article>')
                count += 1
        columns = {row[1] for row in db.execute('PRAGMA table_info(dictionaries)')}
        if 'has_kanji' in columns:
            # Legacy kanji/hanzi dictionaries use term banks; match only the exact glyph.
            for title, glossary in db.execute(f'''SELECT d.title,e.glossary FROM entries e
                JOIN dictionaries d ON d.id=e.dictionary_id
                WHERE e.term=? AND d.has_kanji=1 AND {condition}
                ORDER BY d.sort_order,d.id,e.rowid''', args):
                chunks.append('<article class="kanji-entry"><small>' + html.escape(title) + '</small><div class="definition">' + render(json.loads(glossary)) + '</div></article>')
                count += 1
        if not count:
            chunks.append('<p class="empty">No character entry in the enabled dictionaries. Add a kanji or hanzi dictionary in Dictionaries.</p>')
        chunks.append('</section>')
        return ''.join(chunks)
    finally:
        db.close()


class CharacterLookup(AsyncLookup):
    def __init__(self, parent, path):
        super().__init__(parent)
        self.path = path

    def submit(self, character, enabled_ids=None):
        self.cancel()
        self.cancelled = Event()
        self.query = character
        self.pending = self.executor.submit(lookup_character, character, self.cancelled, self.path, enabled_ids)
        self.poll.start()
