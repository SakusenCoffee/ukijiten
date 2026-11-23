import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yomitan_goldendict as manager
from entry_metadata import MetadataCache, selected_rows, sources
from popup_settings import PopupSettings


class MetadataTests(unittest.TestCase):
    def test_dictionary_example_markup_gets_separate_style(self):
        output=manager.render({'tag':'div','data':{'content':'examples'},'content':[{'tag':'span','content':'先生が来た。'}]})
        self.assertIn('class="example-sentence"',output)
        self.assertNotIn('example-sentence',manager.render({'tag':'div','content':'definition'}))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.patch_dir = patch.object(manager, 'APP_DIR', self.root)
        self.patch_db = patch.object(manager, 'DB_PATH', self.root / 'dictionaries.sqlite3')
        self.patch_dir.start(); self.patch_db.start()
        self.addCleanup(self.patch_dir.stop); self.addCleanup(self.patch_db.stop)
        self.db = manager.connect()
        self.addCleanup(self.db.close)

    def archive(self, title, rows, bank='term_meta_bank_1.json'):
        path = self.root / (title + '.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('index.json', json.dumps({'title': title, 'format': 3}))
            archive.writestr(bank, json.dumps(rows))
        return path

    def load(self, *paths):
        importer = manager.Importer(list(paths))
        messages = []
        importer.finished.connect(messages.append)
        importer.run()
        return messages[0]

    def test_metadata_only_zip_import_and_reimport(self):
        path = self.archive('Frequency', [['先生', 'freq', 24]])
        self.assertEqual(manager.archive_info(path), 'Frequency')
        self.assertIn('1 imported', self.load(path))
        self.assertEqual(self.db.execute('SELECT count,has_frequency,has_pitch FROM dictionaries').fetchone(), (1, 1, 0))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM entries').fetchone()[0], 0)
        self.assertTrue(sources(self.db)[0]['frequency'])
        self.assertIn('1 already indexed', self.load(path))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM term_metadata').fetchone()[0], 1)
        # Old imports are upgraded; failed replacements must preserve the prior data.
        with self.db:
            self.db.execute("UPDATE dictionaries SET stamp='legacy'")
        self.assertIn('1 imported', self.load(path))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM term_metadata').fetchone()[0], 1)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('index.json', '{"title":"Frequency"}')
            archive.writestr('term_meta_bank_1.json', 'broken json')
        self.assertIn('Errors:', self.load(path))
        self.assertEqual(self.db.execute('SELECT data FROM term_metadata').fetchone()[0], '24')

    def test_multiple_selected_sources_reading_match_and_formats(self):
        first = self.archive('First', [
            ['先', 'freq', {'reading': 'せん', 'frequency': {'value': 23, 'displayValue': '23★'}}],
            ['先', 'freq', {'reading': 'さき', 'frequency': 999}],
            ['先生', 'freq', {'value': 25}],
            ['先生', 'freq', '<26>'],
        ])
        second = self.archive('Second', [['先', 'freq', 40]])
        pitch = self.archive('Pitch', [
            ['先', 'pitch', {'reading': 'セン', 'pitches': [{'position': 1}]}],
            ['先', 'pitch', {'reading': 'サキ', 'pitches': [{'position': 0}]}],
            ['先', 'pitch', {'reading': 'セン', 'pitches': [{'position': 99}]}],
        ])
        self.load(first, second, pitch)
        # The source selection is independent of definition enable switches.
        with self.db:
            self.db.execute('UPDATE dictionaries SET enabled=0')
        rows = [('先', 'せん'), ('先生', 'せんせい'), ('先', 'さき')]
        result = selected_rows(self.db, rows, [str(first), str(second)], [str(pitch)])
        self.assertIn('23★', result[('先', 'せん')]); self.assertIn('40', result[('先', 'せん')])
        self.assertNotIn('999', result[('先', 'せん')])
        self.assertIn('[1]', result[('先', 'せん')]); self.assertNotIn('[0]', result[('先', 'せん')])
        self.assertIn('[0]', result[('先', 'さき')]); self.assertNotIn('[1]', result[('先', 'さき')])
        self.assertIn('>25<', result[('先生', 'せんせい')]); self.assertIn('&lt;26&gt;', result[('先生', 'せんせい')])
        self.assertTrue(sources(self.db)[2]['pitch'])
        self.assertEqual(set(selected_rows(self.db, rows, [], []).values()), {''})

    def test_legacy_pitch_and_selection_persistence(self):
        glossary = [{'type': 'structured-content', 'content': {'tag': 'span', 'data': {'pitchAccentText': 'true', 'accentSig': 'セ＼ン'}}}]
        path = self.archive('Legacy pitch', [['先', 'せん', '', '', 0, glossary]], 'term_bank_1.json')
        self.load(path)
        self.assertTrue(sources(self.db)[0]['pitch'])
        self.assertIn('[1]', selected_rows(self.db, [('先', 'せん')], [], [str(path)])[('先', 'せん')])
        settings = PopupSettings(self.root / 'popup.json', [(1, 'Legacy pitch', str(path), 0)])
        settings.update('pitch_paths', [str(path), str(path)])
        settings.update('frequency_paths', ['frequency.zip'])
        restored = PopupSettings(settings.path, [(1, 'Legacy pitch', str(path), 0)])
        self.assertEqual(restored.values['pitch_paths'], [str(path)])
        self.assertEqual(restored.values['frequency_paths'], ['frequency.zip'])

    def test_batched_indexed_queries_cache_hits_and_another_source(self):
        terms=[f'単語{i}' for i in range(100)]
        paths=[self.archive(f'Frequency {source}',[[term,'freq',source*100+i] for i,term in enumerate(terms)]) for source in range(4)]
        glossary=[{'type':'structured-content','content':{'tag':'span','data':{'pitchAccentText':'true','accentSig':'タンゴ━'}}}]
        pitch=self.archive('Pitch',[[term,'たんご','','',0,glossary] for term in terms],'term_bank_1.json')
        self.load(*paths,pitch)
        cache=MetadataCache(manager.DB_PATH)
        entries=[(term,'たんご') for term in terms]*3
        statements=[]
        self.db.set_trace_callback(statements.append)
        result=selected_rows(self.db,entries,[str(path) for path in paths[:2]],[str(pitch)],cache=cache)
        self.assertEqual(len(result),100)
        self.assertEqual(len(statements),4)  # Catalog, table check, metadata batch, pitch batch.
        self.assertIn('INDEXED BY entries_term',statements[-1])
        statements.clear()
        self.assertEqual(selected_rows(self.db,entries,[str(path) for path in paths[:2]],[str(pitch)],cache=cache),result)
        self.assertEqual(len(statements),1)  # Warm lookups check only the small source catalog.
        statements.clear()
        extra=selected_rows(self.db,entries,[str(path) for path in paths],[str(pitch)],cache=cache)
        self.assertEqual(len(statements),4)  # Adding sources does not add per-word SQL probes.
        self.assertIn('Frequency 3',extra[('単語0','たんご')])
        self.assertIn('pitch-graph',extra[('単語0','たんご')])
        self.db.set_trace_callback(None)

    def test_kana_pitch_with_empty_source_reading(self):
        glossary=[{'type':'structured-content','content':{'tag':'span','data':{'pitchAccentText':'true','accentSig':'ア＼ア'}}}]
        path=self.archive('NHK-pitch',[['ああ','','','',0,glossary]],'term_bank_1.json')
        self.load(path)
        result=selected_rows(self.db,[('ああ','ああ'),('ああ','いい')],[],[str(path)])
        self.assertIn('pitch-graph',result[('ああ','ああ')])
        self.assertEqual(result[('ああ','いい')],'')

    def test_source_order_invalidates_cache_and_pitch_uses_one_row(self):
        a=self.archive('Source A',[['先','freq',7],['先','pitch',{'reading':'さき','pitches':[{'position':0}]}]])
        b=self.archive('Source B',[['先','freq',9],['先','pitch',{'reading':'さき','pitches':[{'position':1}]}]])
        self.load(a,b);cache=MetadataCache(manager.DB_PATH)
        first=selected_rows(self.db,[('先','さき')],[str(a),str(b)],[str(a),str(b)],cache=cache)[('先','さき')]
        reverse=selected_rows(self.db,[('先','さき')],[str(b),str(a)],[str(b),str(a)],cache=cache)[('先','さき')]
        self.assertEqual(first.count('class="pitch-row"'),1)
        self.assertEqual(first.count('class="pitch-source"'),2)
        self.assertLess(first.index('Source A'),first.index('Source B'))
        self.assertLess(reverse.index('Source B'),reverse.index('Source A'))
        self.assertLess(reverse.index('Source B pitch accent'),reverse.index('Source A pitch accent'))

    def test_cache_invalidates_after_reimport_remove_and_selection_changes(self):
        path=self.archive('Frequency',[['先','freq',7]])
        self.load(path)
        cache=MetadataCache(manager.DB_PATH,limit=8)
        entries=[('先','さき'),('先生','せんせい')]
        first=selected_rows(self.db,entries,[str(path)],[],cache=cache)
        self.assertIn('>7<',first[entries[0]])
        self.assertEqual(first[entries[1]],'')
        self.archive('Frequency',[['先','freq',14],['先生','freq',99]])
        self.load(path)
        replacement=selected_rows(self.db,entries,[str(path)],[],cache=cache)
        self.assertIn('>14<',replacement[entries[0]])
        self.assertIn('>99<',replacement[entries[1]])
        self.assertEqual(set(selected_rows(self.db,entries,[],[],cache=cache).values()),{''})
        with self.db:self.db.execute('DELETE FROM dictionaries')
        self.assertEqual(set(selected_rows(self.db,entries,[str(path)],[],cache=cache).values()),{''})
        for i in range(20):cache.put(i,str(i))
        self.assertEqual(len(cache.rows),8)


if __name__ == '__main__':
    unittest.main()
