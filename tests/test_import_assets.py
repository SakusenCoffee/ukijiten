import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reading_stats import ReadingStats
from import_assets import import_path, list_assets, remove, import_snapshot
from stats_settings import StatsSettings


class ImportAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=ReadingStats(self.root/'stats.db')
    def tearDown(self):
        self.store.db.close();self.temp.cleanup()

    def test_uploaded_file_list_and_remove_characters_and_time(self):
        path=self.root/'book.csv';path.write_text('text,duration_minutes\n日本語,5\n')
        for _ in range(2):import_path(self.store,path)
        files=list_assets(self.store)
        self.assertEqual(len(files),1);self.assertEqual(files[0]['name'],'book.csv')
        self.assertEqual(self.store.summary()['total'],3);self.assertEqual(self.store.summary()['seconds'],300)
        remove(self.store,files[0]['id'])
        self.assertEqual(self.store.summary()['total'],0);self.assertEqual(self.store.summary()['seconds'],0)
        self.assertTrue(path.exists());self.assertEqual(list_assets(self.store),[])
        import_path(self.store,path);self.assertEqual(self.store.summary()['total'],3)

    def test_overlapping_mokuro_sources_restore_remaining_contribution(self):
        def snapshot(chars,day):return [{'volumes':{'volume':{'chars':chars,'series_title':'Book','lastProgressUpdate':day+'T12:00:00Z'}}}]
        import_snapshot(self.store,snapshot(40,'2026-11-01'),'cloud:google_drive','Google Drive history')
        path=self.root/'progress.json';path.write_text(json.dumps(snapshot(50,'2026-11-02')))
        import_path(self.store,path,'mokuro')
        self.assertEqual(self.store.summary()['total'],50)
        identifier=next(file['id'] for file in list_assets(self.store) if file['path'])
        remove(self.store,identifier)
        self.assertEqual(self.store.summary()['total'],40)
        remove(self.store,'cloud:google_drive');self.assertEqual(self.store.summary()['total'],0)

    def test_legacy_generic_upload_can_be_removed(self):
        path=self.root/'legacy.txt';path.write_text('日本語')
        self.store.import_file(path)
        files=list_assets(self.store);self.assertEqual(len(files),1)
        remove(self.store,files[0]['id']);self.assertEqual(self.store.summary()['total'],0)

    def test_explicit_cloud_refresh_restores_deleted_entries_without_double_counting(self):
        from reading_history import delete_history
        data=[{'volumes':{'book':{'chars':3351,'series_title':'Book','lastProgressUpdate':'2026-11-19T12:00:00Z'}}}]
        import_snapshot(self.store,data,'cloud:webdav','WebDAV')
        delete_history(self.store,{'keys':['manga:book:2026-11-19']})
        import_snapshot(self.store,data,'cloud:webdav','WebDAV');self.assertEqual(self.store.summary()['total'],0)
        for _ in range(2):import_snapshot(self.store,data,'cloud:webdav','WebDAV',restore_deleted=True)
        self.assertEqual(self.store.summary()['total'],3351)

    def test_mokuro_cloud_and_files_respect_day_cutoff(self):
        from datetime import datetime
        self.store.set_preference('day_cutoff_hour',5)
        stamp=datetime(2026,11,19,2).astimezone()
        data=[{'volumes':{'book':{'chars':3351,'series_title':'Book','lastProgressUpdate':stamp.isoformat(),'recentPageTurns':[[stamp.timestamp()*1000,1,3351]]}}}]
        import_snapshot(self.store,data,'cloud:webdav','WebDAV')
        self.assertEqual(self.store.db.execute("SELECT day,characters FROM readings WHERE key LIKE 'manga:book:%'").fetchone(),('2026-11-18',3351))
        path=self.root/'mokuro.json';path.write_text(json.dumps(data));import_path(self.store,path,'mokuro')
        self.assertEqual(self.store.summary()['total'],3351)

    def test_retimed_snapshot_replaces_old_layout_without_duplicate_days(self):
        from datetime import datetime
        data=[{'volumes':{'book':{'chars':40,'series_title':'Book','lastProgressUpdate':datetime(2026,11,19,2).astimezone().isoformat()}}}]
        path=self.root/'mokuro.json';path.write_text(json.dumps(data));import_path(self.store,path,'mokuro')
        self.store.set_preference('day_cutoff_hour',5)
        import_snapshot(self.store,data,'cloud:webdav','WebDAV',restore_deleted=True)
        self.assertEqual(self.store.summary()['total'],40)
        self.assertEqual(self.store.db.execute('SELECT day FROM readings').fetchone()[0],'2026-11-18')
        remove(self.store,'cloud:webdav');self.assertEqual(self.store.summary()['total'],40)

    def test_personal_webdav_settings_migrate_under_mokuro(self):
        settings=self.root/'stats-sources.json'
        settings.write_text(json.dumps({'manga':{'enabled':True,'webdav_server_url':'https://example.org','webdav_username':'user','webdav_password':'secret','webdav_token':''},'mokuro':{'enabled':False,'paths':[]}}))
        config=StatsSettings(self.root)
        self.assertNotIn('manga',config.public())
        self.assertTrue(config.values['mokuro']['enabled'])
        self.assertEqual(config.values['mokuro']['webdav']['webdav_password'],'secret')
        self.assertNotIn('webdav_password',config.public()['mokuro']['webdav'])
        config.save(config.public());restored=StatsSettings(self.root)
        self.assertEqual(restored.values['mokuro']['webdav']['webdav_password'],'secret')

if __name__=='__main__':unittest.main()
