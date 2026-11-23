import json
from pathlib import Path
import tempfile
import unittest
from reading_stats import ReadingStats, japanese_characters


class ReadingStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ReadingStats(self.root / 'stats.db')

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_japanese_only_including_written_numbers(self):
        self.assertEqual(japanese_characters('一二三、よん。五 123４５６abc!?😀 カナ ｶﾅ 𠮷 〇々'), '一二三よん五カナカナ𠮷〇々')
        self.assertEqual(japanese_characters('！？・「」12345１２３㊙'), '')

    def event(self, text, revision=0, **extras):
        row = dict(id='line1', session_id='game1', text=text, revision=revision, scene='Test game', captured_at='2026-11-12T12:00:00-06:00')
        row.update(extras)
        return json.dumps(dict(event='text_v2_append', data=row))

    def test_revision_replay_and_exclusion(self):
        self.store.ingest(self.event('日本語12。'))
        self.store.ingest(self.event('日本語12。'))
        self.assertEqual(self.store.summary()['total'], 3)
        self.store.ingest(self.event('日本語を読む', 2))
        self.store.ingest(self.event('日本語', 1))
        self.assertEqual(self.store.summary()['total'], 6)
        self.store.ingest(self.event('日本語', 3, excluded_from_stats=True))
        self.assertEqual(self.store.summary()['total'], 0)

    def test_snapshot_and_legacy_do_not_double_count(self):
        record = json.loads(self.event('日本語'))['data']
        self.store.ingest(json.dumps({'event':'text_v2_snapshot','lines':[record]}))
        self.store.ingest(self.event('日本語'))
        self.store.ingest(json.dumps({'event':'text_received','data':record}))
        self.assertEqual(self.store.summary()['total'], 3)

    def test_csv_import_and_reimport(self):
        path = self.root / 'kechimochi.csv'
        path.write_text('Date,Log Name,Language,Characters,Duration\n2026-11-01,Book,Japanese,100,10\n2026-11-02,Book,English,200,5\n', encoding='utf8')
        self.assertEqual(self.store.import_file(path), 1)
        self.assertEqual(self.store.import_file(path), 0)
        self.assertEqual(self.store.summary()['total'], 100)
        self.assertEqual(self.store.summary()['seconds'], 600)

    def test_text_import_filters_symbols_and_failed_import_is_atomic(self):
        path = self.root/'text.txt';path.write_text('日本語123!\n一二三。\nabc123')
        self.store.import_file(path)
        self.assertEqual(self.store.summary()['total'], 6)
        bad = self.root/'bad.json';bad.write_text(json.dumps([{'characters':10},{'date':'bad','characters':30}]))
        with self.assertRaises(ValueError):self.store.import_file(bad)
        self.assertEqual(self.store.summary()['total'], 6)

    def test_persistence_and_same_day_active_time(self):
        self.store.ingest(self.event('日本語'))
        self.store.ingest(self.event('読む',id='line2',captured_at='2026-11-12T12:00:30-06:00'))
        self.store.ingest(self.event('本',id='line3',captured_at='2026-11-12T13:00:00-06:00'))
        self.assertEqual(self.store.summary()['seconds'],30)
        other=ReadingStats(self.root/'stats.db')
        self.assertEqual(other.summary()['total'],6)
        other.db.close()
        self.store.ingest(self.event('次',id='line4',captured_at='2026-11-12T13:01:30-06:00'))
        self.assertEqual(self.store.summary()['seconds'],120)
        self.store.ingest(self.event('終',id='line5',captured_at='2026-11-12T13:03:01-06:00'))
        self.assertEqual(self.store.summary()['seconds'],120)

    def test_source_aliases_combine_sky_but_keep_kuro(self):
        names = ['Sora no Kiseki FC', 'sora no kiseki', 'Trails in the Sky 1st Chapter', 'Kuro no Kiseki']
        for index, name in enumerate(names):
            self.store.record(str(index), '日本語', name)
        self.store.set_preference('source_aliases', {name: 'Trails in the Sky' for name in names[:3]})
        summary = self.store.summary()
        self.assertEqual({row['source']: row['characters'] for row in summary['sources']},
            {'Trails in the Sky': 9, 'Kuro no Kiseki': 3})
        self.assertEqual(summary['total'], 12)
        self.assertEqual(len(summary['recent']), 2)

    def test_manual_entries_include_time_only_reading_and_retry_is_idempotent(self):
        identifier='0ae446d7-950f-4f0a-8a66-087fb9e7179b'
        for _ in range(2):
            self.store.add_manual_entry(120,1,15,'My reading','2026-11-10',identifier)
        self.store.add_manual_entry(0,0,30,'Time only','2026-11-11')
        summary=self.store.summary()
        self.assertEqual(summary['total'],120)
        self.assertEqual(summary['reading_seconds'],6300)
        self.assertEqual(summary['consistency_days']['2026-11-11']['seconds'],1800)
        self.assertEqual(summary['anki_seconds'],0)
        self.assertEqual(summary['active_days'],2)
        with self.assertRaises(ValueError):self.store.add_manual_entry(0,0,0,'')
        with self.assertRaises(ValueError):self.store.add_manual_entry(10,0,60,'')
        with self.assertRaises(ValueError):self.store.add_manual_entry(-1,1,0,'')
