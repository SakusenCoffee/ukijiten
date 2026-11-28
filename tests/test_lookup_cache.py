import sqlite3
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from async_lookup import lookup, prepare_lookup
from dictionary_search import search_entries
from dictionary_render import render, render_definition
from lookup_cache import ByteCache
from test_performance import database


class CacheTests(unittest.TestCase):
    def test_bounds_and_lru(self):
        cache = ByteCache(max_bytes=10, max_entries=2)
        cache.put('a', 'A', 4); cache.put('b', 'B', 4)
        self.assertEqual(cache.get('a'), 'A')
        cache.put('c', 'C', 4)
        self.assertIsNone(cache.get('b'))
        cache.put('a', 'replacement', 20)
        self.assertIsNone(cache.get('a'))
        self.assertLessEqual(cache.bytes, 10)

    def test_wal_changes_and_result_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite'
            db = database(path)
            self.addCleanup(db.close)
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('UPDATE dictionaries SET sort_order=sort_order+1'); db.commit()
            with patch('async_lookup.search_entries', wraps=search_entries) as search:
                first = lookup('先', Event(), path)
                lookup('先', Event(), path)
                self.assertEqual(search.call_count, 1)
                first.clear()
                self.assertTrue(lookup('先', Event(), path))
                db.execute('UPDATE dictionaries SET enabled=0 WHERE id=2'); db.commit()
                self.assertEqual({r[3] for r in lookup('先', Event(), path)}, {1})
                self.assertEqual(search.call_count, 2)
                db.execute('UPDATE entries SET glossary=? WHERE term=?', ('["updated"]', '先')); db.commit()
                self.assertEqual(lookup('先', Event(), path)[0][2], '["updated"]')
                cancelled = Event(); cancelled.set()
                self.assertEqual(lookup('先', cancelled, path), [])

    def test_preparation_preserves_markup_and_bad_definition_behavior(self):
        import json
        raw = json.dumps([{'tag':'ruby','content':'字'}, '<script>'])
        rows = [('字', 'じ', raw, 1, 'Test'), ('悪', 'あく', '{bad', 1, 'Test')]
        prepared = prepare_lookup(lambda *args: rows, '字', Event(), None, ((), ()))
        self.assertEqual(prepared, rows)
        self.assertEqual(prepared.definitions[raw], render(json.loads(raw)))
        self.assertIsNone(prepared.definitions['{bad'])
        self.assertEqual(render_definition(raw), prepared.definitions[raw])
