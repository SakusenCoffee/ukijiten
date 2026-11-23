import json
from pathlib import Path
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yomitan_goldendict as manager
from character_lookup import headword_markup, is_character, lookup_character
from entry_metadata import sources


class CharacterLookupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / 'dictionary.sqlite3'
        for name, value in [('APP_DIR', self.root), ('DB_PATH', self.path)]:
            patcher = patch.object(manager, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        self.db = manager.connect()
        self.addCleanup(self.db.close)

    def archive(self, name, banks):
        path = self.root / (name + '.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('index.json', json.dumps({'title': name, 'format': 3}))
            for bank, data in banks.items():
                archive.writestr(bank, json.dumps(data, ensure_ascii=False))
        return path

    def load(self, *paths):
        importer = manager.Importer(paths)
        messages = []
        importer.finished.connect(messages.append)
        importer.run()
        return messages[-1]

    def lookup(self, char, ids=None):
        return lookup_character(char, Event(), self.path, ids)

    def test_native_entries_frequency_and_stats_are_separate_from_words(self):
        path = self.archive('Characters', {
            'kanji_bank_1.json': [['読', 'ドク', 'よ.む', 'common', ['read <script>'], {'strokes': '14'}]],
            'kanji_meta_bank_1.json': [['読', 'freq', {'value': 12, 'displayValue': '12 (400)'}]],
            'tag_bank_1.json': [['strokes', 'misc', 0, 'Stroke count', 0]],
        })
        self.assertEqual(manager.archive_info(path), 'Characters')
        self.assertIn('1 imported', self.load(path))
        result = self.lookup('読')
        for text in ('ドク', 'よ.む', 'read &lt;script&gt;', 'Stroke count', '14', '12 (400)'):
            self.assertIn(text, result)
        self.assertEqual(manager.search_entries(self.db, '読'), [])
        capabilities = sources(self.db)[0]
        self.assertTrue(capabilities['kanji']); self.assertTrue(capabilities['kanji_frequency'])
        self.assertFalse(capabilities['frequency'])
        self.assertIn('1 already indexed', self.load(path))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM kanji_entries').fetchone()[0], 1)

    def test_chinese_and_supplementary_hanzi_match_exactly(self):
        path = self.archive('Hanzi', {'kanji_bank_1.json': [
            ['汉', 'hàn', '', '', ['Chinese; Han'], {}],
            ['漢', 'hàn', '', '', ['Traditional form'], {}],
            ['𠮟', 'chì', '', '', ['Supplementary character'], {}],
        ]})
        self.load(path)
        self.assertIn('Chinese; Han', self.lookup('汉'))
        self.assertNotIn('Traditional form', self.lookup('汉'))
        self.assertIn('hàn', self.lookup('漢'))
        self.assertIn('Supplementary character', self.lookup('𠮟'))
        for glyph in ('汉', '漢', '𠮟', '﨑'):
            self.assertTrue(is_character(glyph))
        markup = headword_markup('お漢字𠮟<&')
        self.assertEqual(markup.count('data-character='), 3)
        self.assertIn('data-character="𠮟"', markup)
        self.assertIn('&lt;&amp;', markup)
        self.assertFalse(is_character('漢字')); self.assertFalse(is_character('a'))

    def test_enabled_selection_and_missing_entries(self):
        first = self.archive('First', {'kanji_bank_1.json': [['先', '', '', '', ['first definition'], {}]]})
        second = self.archive('Second', {'kanji_bank_1.json': [['先', '', '', '', ['second definition'], {}]]})
        freq = self.archive('Freq', {'kanji_meta_bank_1.json': [['先', 'freq', 15]]})
        self.load(first, second, freq)
        with self.db:
            self.db.execute('UPDATE dictionaries SET enabled=0 WHERE id=1')
        self.assertNotIn('first definition', self.lookup('先'))
        self.assertIn('first definition', self.lookup('先', [1]))
        self.assertNotIn('second definition', self.lookup('先', [1]))
        self.assertNotIn('>15<', self.lookup('先', [1]))
        self.assertIn('No character entry', self.lookup('先', []))
        self.assertIn('No character entry', self.lookup('無'))
        cancelled = Event(); cancelled.set()
        self.assertEqual(lookup_character('先', cancelled, self.path), '')

    def test_legacy_character_term_banks_and_failed_reimport(self):
        path = self.archive('[Kanji] Legacy', {'term_bank_1.json': [
            ['読', '', '', '', 0, ['Legacy definition']],
            ['読書', '', '', '', 0, ['Compound']],
        ]})
        self.load(path)
        self.assertIn('Legacy definition', self.lookup('読'))
        self.assertEqual(manager.search_entries(self.db, '読'), [])
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('index.json', '{"title":"Broken"}')
            archive.writestr('kanji_bank_1.json', 'invalid JSON')
        self.assertIn('Errors:', self.load(path))
        self.assertIn('Legacy definition', self.lookup('読'))
        self.assertEqual(self.db.execute('SELECT title FROM dictionaries').fetchone()[0], '[Kanji] Legacy')


if __name__ == '__main__':
    unittest.main()
