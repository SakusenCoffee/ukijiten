from datetime import date,timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reading_stats import ReadingStats
from import_assets import import_path,list_assets,remove
from cloud_dialog import browser_answer
from browser_cloud import BrowserCloudConnection
from mokuro_cloud import config_command
from unittest.mock import MagicMock, patch


class RefinementTests(unittest.TestCase):
    def test_streak_combines_reading_and_anki_days_without_double_counting(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ReadingStats(Path(folder)/'stats.db');today=date.today()
            for ago in (0,2):store.add_manual_entry(1,0,0,'Book',(today-timedelta(days=ago)).isoformat())
            with store.db:
                for ago in (0,1):store.db.execute('INSERT INTO anki_daily VALUES (?,?,?)',((today-timedelta(days=ago)).isoformat(),1000,1))
            stats=store.summary();self.assertEqual(stats['streak'],3);self.assertEqual(stats['longest'],3)
            self.assertEqual(stats['total'],2);self.assertEqual(stats['active_days'],2)
            store.db.close()

    def test_plain_texthooker_and_json_text_are_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ReadingStats(Path(folder)/'stats.db')
            store.ingest('日本語');store.ingest('日本語')
            store.ingest(json.dumps({'text':'読む'}));store.ingest(json.dumps('本'))
            self.assertEqual(store.summary()['total'],6);store.db.close()

    def test_ttsu_zip_and_json_use_recorded_seconds(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            rows=[{'title':'Book','dateKey':'2026-11-01','charactersRead':100,'readingTime':125},
                  {'title':'Book','dateKey':'2026-11-02','charactersRead':0,'readingTime':10}]
            path=folder/'ttsu.zip'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('Book/statistics_123.json',json.dumps(rows))
                archive.writestr('Book/bookdata.epub','Ignored book data')
            store=ReadingStats(folder/'stats.db');import_path(store,path)
            self.assertEqual(store.summary()['total'],100);self.assertEqual(store.summary()['seconds'],135)
            file=list_assets(store)[0];remove(store,file['id']);self.assertEqual(store.summary()['seconds'],0)
            direct=folder/'statistics.json';direct.write_text(json.dumps(rows));import_path(store,direct)
            self.assertEqual(store.summary()['seconds'],135);store.db.close()

    def test_browser_answers_are_delivered_as_real_cli_flags(self):
        with tempfile.TemporaryDirectory() as directory,patch('mokuro_cloud.binary',return_value='rclone'):
            connection=BrowserCloudConnection(directory,'onedrive')
            process=MagicMock();process.communicate.return_value=('{}','');process.returncode=0
            try:
                command=config_command(directory,'onedrive','state','true')
                with patch('browser_cloud.subprocess.Popen',return_value=process) as start:
                    connection.command(command)
                arguments=start.call_args.args[0]
                self.assertIn('--result',arguments)
                self.assertEqual(arguments[arguments.index('--result')+1],'true')
            finally:connection.close()

    def test_browser_setup_never_chooses_headless_or_custom_client(self):
        for name in ('config_is_local','config_shared_client_id','config_browser'):
            self.assertEqual(browser_answer(name),'true')
        self.assertIsNone(browser_answer('config_driveid'))

if __name__=='__main__':unittest.main()
