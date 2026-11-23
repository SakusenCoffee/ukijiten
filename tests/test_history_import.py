import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from history_import import import_gsm, import_manga, manga_records
from reading_stats import ReadingStats, gsm_line_key

class HistoryImportTests(unittest.TestCase):
    def test_volume_titles_separate_history_without_adding_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=ReadingStats(root/'stats.db');self.addCleanup(store.db.close)
            path=root/'history.json'
            data=[{'volumes':{'seven':{'series_title':'Series','chars':11774,
                'timeReadInMinutes':139,'lastProgressUpdate':'2026-11-23T01:58:42Z'}}}]
            path.write_text(json.dumps(data));import_manga(store,path)
            before=store.summary()
            data[0]['volumes']['seven']['volume_title']='Series 第07巻'
            path.write_text(json.dumps(data));import_manga(store,path);import_manga(store,path)
            after=store.summary()
            self.assertEqual(after['total'],before['total'])
            self.assertEqual(after['seconds'],before['seconds'])
            self.assertEqual(after['recent'][0]['source'],'Manga · Series 第07巻')

    def test_manga_daily_deltas_alias_deduplication_and_reimport(self):
        row={'chars':100,'timeReadInMinutes':10,'series_title':'Test manga','lastProgressUpdate':'2026-11-02T12:00:00Z',
             'recentPageTurns':[[1793534400000,1,20],[1793534430000,2,40],[1793620800000,3,100]]}
        snapshots=[{'volumes':{'volume':row}},{'volumes':{'volume':row}}]
        records=manga_records(snapshots)
        self.assertEqual(sum(r[3] for r in records),100)
        self.assertAlmostEqual(sum(r[4] for r in records),600)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=ReadingStats(root/'ledger.db');file=root/'manga.json';file.write_text(json.dumps(snapshots))
            import_manga(store,file);import_manga(store,file)
            self.assertEqual(store.summary()['total'],100);store.db.close()

    def test_gsm_history_and_live_share_uuid(self):
        identifier='0ae446d7-950f-4f0a-8a66-087fb9e7179b'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=sqlite3.connect(root/'gsm.db')
            db.executescript('CREATE TABLE game_lines(id,game_id,game_name,line_text,timestamp,language);CREATE TABLE games(id,obs_scene_name,title_original,title_romaji);CREATE TABLE game_daily_rollup(date,game_id,total_reading_time_seconds);')
            db.execute('INSERT INTO game_lines VALUES (?,?,?,?,?,?)',(identifier,'game','Test','日本語123。',1794492000,'ja'));db.commit();db.close()
            store=ReadingStats(root/'ledger.db')
            store.record('gsm:session:'+identifier,'日本語123。','Test','2026-11-12T10:00:00Z')
            store.db.close();store=ReadingStats(root/'ledger.db')
            import_gsm(store,root/'gsm.db');import_gsm(store,root/'gsm.db')
            store.ingest(json.dumps({'event':'text_v2_append','data':{'id':identifier,'session_id':'another','text':'日本語123。','scene':'Test','captured_at':'2026-11-12T20:40:00Z'}}))
            self.assertEqual(store.summary()['total'],3)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM readings').fetchone()[0],1)
            self.assertTrue(gsm_line_key(identifier).startswith('gsm-line:'))
            store.db.close()
