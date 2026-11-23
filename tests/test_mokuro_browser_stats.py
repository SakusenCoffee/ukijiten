import sqlite3
import sys
import tempfile
import unittest
import time
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reading_stats import ReadingStats
from reading_history import delete_history
from mokuro_browser_stats import sync_history, fingerprint


class BrowserStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.path = root/'browser.sqlite3'
        self.source = sqlite3.connect(self.path); self.addCleanup(self.source.close)
        self.source.execute('CREATE TABLE pages(id TEXT PRIMARY KEY,title TEXT,scanned_at REAL,text TEXT,deleted INTEGER)')
        self.store = ReadingStats(root/'stats.sqlite3'); self.addCleanup(self.store.db.close)
        self.stamp = datetime(2026,11,22,2).astimezone().timestamp()

    def page(self,key,text,offset=0,deleted=0):
        with self.source:self.source.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?)',(key,'Book',self.stamp+offset,text,deleted))

    def test_import_replay_edit_and_source_delete(self):
        self.page('one','漢字ひらカナABC123'); self.page('two','日本語',30)
        self.page('deleted','未読',deleted=1)
        self.assertEqual(sync_history(self.store,self.path),2)
        original = self.store.summary()
        self.assertEqual(original['total'],9)
        self.assertEqual(original['reading_seconds'],30)
        self.assertEqual(original['scripts'],dict(kanji=5,hiragana=2,katakana=2,unclassified=0))
        self.assertEqual(sync_history(self.store,self.path),0)
        self.assertEqual(self.store.summary()['total'],9)
        self.page('one','カタカナひら')  # Same count, different script distribution.
        self.assertEqual(sync_history(self.store,self.path),1)
        self.assertEqual(self.store.summary()['scripts']['kanji'],3)
        self.page('two','日本語',30,deleted=1);sync_history(self.store,self.path)
        self.assertEqual(self.store.summary()['total'],6)

    def test_local_deletion_not_restored_by_live_sync(self):
        self.page('one','日本語');sync_history(self.store,self.path)
        delete_history(self.store,{'keys':['mokuro-browser:one']})
        sync_history(self.store,self.path)
        self.assertEqual(self.store.summary()['total'],0)

    def test_cutoff_and_source_metrics(self):
        self.store.set_preference('day_cutoff_hour',5)
        self.page('one','日本語'); self.page('two','かな',30);sync_history(self.store,self.path)
        self.assertEqual(self.store.summary()['days']['2026-11-21']['characters'],5)
        self.store.set_preference('source_metrics',{'mokuro_browser':{'include_characters':False,'include_time':True}})
        data=self.store.summary(); self.assertEqual(data['total'],0);self.assertEqual(data['reading_seconds'],30)
        self.assertEqual(data['scripts']['kanji'],0)
        self.store.set_preference('source_metrics',{'mokuro_browser':{'include_characters':True,'include_time':False}})
        self.assertEqual(self.store.summary()['total'],5);self.assertEqual(self.store.summary()['reading_seconds'],0)

    def test_wal_changes_detected_and_source_is_not_modified(self):
        self.source.execute('PRAGMA journal_mode=WAL');self.page('one','漢字')
        before=fingerprint(self.path);sync_history(self.store,self.path)
        self.assertEqual(fingerprint(self.path),before)
        self.page('two','カナ',10);self.assertNotEqual(fingerprint(self.path),before)
        self.assertEqual(sync_history(self.store,self.path),1)

    def test_old_numeric_imports_stay_unclassified(self):
        self.store.add_manual_entry(100,0,0,'Old total')
        self.page('one','漢あア');sync_history(self.store,self.path)
        self.assertEqual(self.store.summary()['scripts'],dict(kanji=1,hiragana=1,katakana=1,unclassified=100))

    def test_legacy_gsm_text_backfill_never_adds_readings(self):
        from reading_scripts import backfill_gsm_text
        source=Path(self.temp.name)/'gsm.sqlite3'
        with sqlite3.connect(source) as db:
            db.execute('CREATE TABLE game_lines(id TEXT,line_text TEXT)')
            db.executemany('INSERT INTO game_lines VALUES (?,?)',[('old','漢字'),('unrelated','未読')])
        with self.store.db:self.store.db.execute("INSERT INTO readings VALUES ('gsm-line:old','2026-11-22','Book',2,0,'live',0,0)")
        self.assertEqual(backfill_gsm_text(self.store,source),1)
        self.assertEqual(self.store.summary()['total'],2)
        self.assertEqual(self.store.summary()['scripts']['kanji'],2)
        self.assertEqual(backfill_gsm_text(self.store,source),0)

    def test_live_feed_imports_new_pages_and_respects_disable(self):
        from PySide6.QtCore import QCoreApplication
        from mokuro_browser_feed import MokuroBrowserFeed
        app=QCoreApplication.instance() or QCoreApplication([])
        self.page('one','漢字')
        notifications=[]
        feed=MokuroBrowserFeed(Path(self.temp.name)/'stats.sqlite3',
            {'enabled':True,'path':str(self.path)},lambda:notifications.append(True))
        self.addCleanup(feed.close)
        def wait_for(total):
            deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                app.processEvents();time.sleep(.01)
                if self.store.summary()['total']==total and feed.future is None:return
            self.fail('Live page update was not imported')
        wait_for(2)
        self.assertFalse(feed.is_live)
        with patch('mokuro_browser_feed.browser_server_running',return_value=True):
            feed.update();self.assertTrue(feed.is_live)
        with patch('mokuro_browser_feed.browser_server_running',return_value=False):
            feed.update();self.assertFalse(feed.is_live)
        self.assertEqual(self.store.summary()['total'],2)
        self.page('two','かな',30);wait_for(4)
        self.assertTrue(notifications)
        feed.configure({'enabled':False,'path':str(self.path)})
        self.page('three','カナ',40);feed.update()
        self.assertIsNone(feed.future);self.assertEqual(self.store.summary()['total'],4)
        feed.configure({'enabled':True,'path':str(self.path)});wait_for(6)
        feed.close()

    def test_running_status_matches_process_and_database_not_saved_history(self):
        from mokuro_browser_feed import browser_server_running
        proc=Path(self.temp.name)/'proc';proc.mkdir();process=proc/'123';process.mkdir()
        command=process/'cmdline'
        self.page('one','漢字')
        self.assertFalse(browser_server_running(self.path,proc))
        command.write_bytes(b'python\0-m\0mokuro_browser\0serve\0--history-file\0'+str(self.path).encode()+b'\0')
        self.assertTrue(browser_server_running(self.path,proc))
        self.assertFalse(browser_server_running(self.path.with_name('other.db'),proc))
        command.write_bytes(b'python\0other_app.py\0mokuro_browser\0serve\0')
        self.assertFalse(browser_server_running(self.path,proc))


if __name__=='__main__':unittest.main()
