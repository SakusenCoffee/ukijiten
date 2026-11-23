import base64
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import unittest
from history_import import import_manga
from reading_stats import ReadingStats
from stats_refresh import fetch_webdav,refresh_sources


class RefreshTests(unittest.TestCase):
    def test_authenticated_fetch_refresh_and_repeated_refresh(self):
        row={'chars':42,'series_title':'Book','lastProgressUpdate':'2026-11-12T12:00:00Z'}
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                if self.headers.get('Authorization')!='Basic '+base64.b64encode(b'user:secret').decode():
                    self.send_response(401);self.end_headers();return
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'volume':row}).encode())
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);connection=root/'connection.json';database=root/'stats.db'
                connection.write_text(json.dumps({'webdav_server_url':f'http://127.0.0.1:{server.server_port}', 'webdav_username':'user','webdav_password':'secret'}))
                for _ in range(2):
                    result=refresh_sources(database,[],connection)
                    self.assertIn('Mokuro WebDAV updated',result)
                store=ReadingStats(database)
                self.assertEqual(store.summary()['total'],42)
                connection.write_text(connection.read_text().replace('secret','wrong'))
                result=refresh_sources(database,[],connection)
                self.assertIn('login needs updating',result)
                self.assertEqual(store.summary()['total'],42)
                self.assertEqual(calls,['/mokuro-reader/volume-data.json']*3)
                store.db.close()
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_corrected_history_replaces_old_days_and_older_snapshot_cannot_regress(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=ReadingStats(root/'stats.db');path=root/'progress.json'
            def snapshot(chars,date):
                path.write_text(json.dumps([{'volumes':{'volume':{'chars':chars,'series_title':'Book','lastProgressUpdate':date}}}]))
                import_manga(store,path)
            snapshot(100,'2026-11-01T12:00:00Z')
            snapshot(110,'2026-11-02T12:00:00Z')
            self.assertEqual(store.summary()['total'],110)
            self.assertNotIn('2026-11-01',store.summary()['days'])
            snapshot(100,'2026-11-01T12:00:00Z')
            self.assertEqual(store.summary()['total'],110)
            store.db.close()
