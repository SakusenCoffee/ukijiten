import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reading_stats import ReadingStats,gsm_line_key,ocr_text_digest
from reading_history import query_history,delete_history,history_text
from history_import import import_gsm
from import_assets import import_path,initialize,remove


class ReadingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        self.store=ReadingStats(self.root/'stats.db');self.addCleanup(self.store.db.close)
        self.store.record('line:1','先生です','Book A','2026-11-18T12:00:00-06:00')
        self.store.record('line:2','学校へ行く','Book A','2026-11-18T12:00:20-06:00')
        self.store.record('line:3','雨です','Book B','2026-11-17T12:00:00-06:00')

    def test_grouped_and_individual_history_filter_page_and_saved_text(self):
        page=query_history(self.store,{'limit':1});self.assertEqual(page['total'],2);self.assertEqual(page['records'],3)
        self.assertEqual(page['entries'][0]['records'],2);self.assertEqual(page['entries'][0]['characters'],9)
        self.assertEqual(query_history(self.store,{'offset':1,'limit':1})['entries'][0]['source'],'Book B')
        entries=query_history(self.store,{'source':'Book A','grouped':False})['entries'];self.assertEqual(len(entries),2)
        self.assertEqual(history_text(self.store,'line:1')['text'],'先生です')
        self.assertEqual(query_history(self.store,{'search':'学校'})['records'],1)

    def test_multi_delete_exact_group_and_individual_and_live_replay_does_not_restore(self):
        deleted=delete_history(self.store,{'groups':[{'day':'2026-11-18','source':'Book A','kind':'live'}],'keys':['line:3']})
        self.assertEqual(deleted['deleted'],3);self.assertEqual(self.store.summary()['total'],0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM reading_texts').fetchone()[0],0)
        self.assertFalse(self.store.record('line:1','先生です','Book A',revision=20));self.assertEqual(self.store.summary()['total'],0)
        with self.assertRaises(ValueError):history_text(self.store,'line:1')

    def test_search_selected_group_only_deletes_matching_lines(self):
        result=delete_history(self.store,{'groups':[{'day':'2026-11-18','source':'Book A','kind':'live','search':'学校'}]})
        self.assertEqual(result['deleted'],1);self.assertEqual(query_history(self.store,{})['records'],2)

    def test_all_matching_and_invalid_requests_are_transactional(self):
        with self.assertRaises(ValueError):delete_history(self.store,{'groups':[{'day':'bad date','source':'Book A','kind':'live'}]})
        self.assertEqual(query_history(self.store,{})['records'],3)
        result=delete_history(self.store,{'all_matching':True,'filter':{'source':'Book A'}})
        self.assertEqual(result['deleted'],2);self.assertEqual(query_history(self.store,{})['records'],1)

    def test_imported_text_survives_ownership_and_deletion_survives_reimport(self):
        path=self.root/'readings.csv';path.write_text('Date,Source,Text\n2026-11-18,Imported book,こんにちは\n2026-11-18,Imported book,さようなら\n')
        import_path(self.store,path)
        entries=query_history(self.store,{'source':'Imported book','grouped':False})['entries'];self.assertEqual(len(entries),2)
        self.assertTrue(history_text(self.store,entries[0]['key'])['available'])
        delete_history(self.store,{'keys':[entries[0]['key']]});import_path(self.store,path)
        self.assertEqual(query_history(self.store,{'source':'Imported book'})['records'],1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM reading_texts WHERE key=?',(entries[0]['key'],)).fetchone()[0],0)

    def test_older_import_text_can_be_recovered_from_original_file(self):
        path=self.root/'readings.txt';path.write_text('先生です\n学校です\n');import_path(self.store,path)
        key=query_history(self.store,{'source':'readings','grouped':False})['entries'][0]['key']
        self.store.db.execute('DELETE FROM reading_texts WHERE key=?',(key,));self.store.db.commit()
        self.assertTrue(history_text(self.store,key)['available'])

    def test_read_only_recovery_from_gsm_database_and_retired_local_echo(self):
        path=self.root/'gsm.db'
        with sqlite3.connect(path) as source:source.execute('CREATE TABLE game_lines(id TEXT PRIMARY KEY,line_text TEXT)');source.execute('INSERT INTO game_lines VALUES (?,?)',('original-id','昔の記録'))
        key=gsm_line_key('original-id');self.store.record(key,'昔の記録','GSM')
        self.store.db.execute('DELETE FROM reading_texts WHERE key=?',(key,));self.store.db.commit()
        self.assertEqual(history_text(self.store,key,[path])['text'],'昔の記録')
        self.store.db.execute("INSERT INTO readings VALUES ('game-ocr:legacy','2026-11-18','Old local',4,0,'live',0,0)")
        self.store.db.execute('INSERT INTO game_ocr_echoes VALUES (?,?,?)',(key,'game-ocr:legacy',ocr_text_digest('昔の記録')));self.store.db.commit()
        self.assertEqual(history_text(self.store,'game-ocr:legacy',[path])['text'],'昔の記録')
        result=delete_history(self.store,{'keys':['game-ocr:legacy']});self.assertTrue(result['deleted'])
        self.assertFalse(self.store.record(key,'昔の記録','GSM',revision=30))
        with sqlite3.connect(path) as source:self.assertEqual(source.execute('SELECT COUNT(*) FROM game_lines').fetchone()[0],1)

    def test_sources_without_text_report_unavailable(self):
        self.store.add_manual_entry(10,0,5,'Manual',day='2026-11-18')
        key=query_history(self.store,{'source':'Manual','grouped':False})['entries'][0]['key']
        self.assertFalse(history_text(self.store,key)['available'])

    def test_feed_replay_backfills_text_without_changing_totals(self):
        self.store.db.execute("DELETE FROM reading_texts WHERE key='line:1'");self.store.db.commit()
        self.assertFalse(self.store.record('line:1','先生です','Book A','2026-11-18T12:00:00-06:00'))
        self.assertEqual(history_text(self.store,'line:1')['text'],'先生です')
        self.assertEqual(self.store.summary()['total'],12)

    def test_day_boundary_applies_to_live_history_only(self):
        from datetime import datetime
        self.store.set_preference('day_cutoff_hour',2)
        stamp=datetime(2026,11,19,1,30).astimezone().isoformat()
        self.store.record('late','昨日','Late reading',stamp)
        self.assertEqual(query_history(self.store,{'source':'Late reading'})['entries'][0]['day'],'2026-11-18')
        self.store.add_manual_entry(5,0,0,'Manual day',day='2026-11-19')
        self.assertEqual(query_history(self.store,{'source':'Manual day'})['entries'][0]['day'],'2026-11-19')

    def test_deleted_gsm_time_does_not_get_redistributed_on_refresh(self):
        path=self.root/'gsm-rollup.db'
        with sqlite3.connect(path) as source:
            source.executescript('CREATE TABLE game_lines(id,game_id,game_name,line_text,timestamp,language);CREATE TABLE games(id,obs_scene_name,title_original,title_romaji);CREATE TABLE game_daily_rollup(date,game_id,total_reading_time_seconds);')
            from datetime import datetime
            stamp=datetime(2026,11,18,12).astimezone().timestamp()
            source.executemany('INSERT INTO game_lines VALUES (?,?,?,?,?,?)',[('a','game','GSM import','先生',stamp,'ja'),('b','game','GSM import','学校',stamp+30,'ja')])
            source.execute('INSERT INTO game_daily_rollup VALUES (?,?,?)',('2026-11-18','game',60))
        import_gsm(self.store,path);delete_history(self.store,{'keys':[gsm_line_key('a')]});import_gsm(self.store,path)
        result=self.store.db.execute("SELECT SUM(characters),SUM(seconds) FROM readings WHERE source='GSM import'").fetchone()
        self.assertEqual(result,(2,30))


if __name__=='__main__':unittest.main()
