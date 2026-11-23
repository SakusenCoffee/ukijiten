import copy
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anki_stats import available_decks, import_connect_reviews, collection_reviews, replace_reviews, config_version
from reading_stats import ReadingStats
from stats_settings import StatsSettings
from stats_refresh import refresh_configured
from test_anki_stats import collection


class SourceSettingsTests(unittest.TestCase):
    def test_settings_validate_persist_and_do_not_expose_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=StatsSettings(directory)
            draft=settings.public()
            draft['gsm']['url']='ws://reader.local:55001/ws/texthooker'
            draft['anki'].update(url='http://localhost:8766',key='secret',decks=['A','A','B::C'])
            settings.save(draft)
            public=settings.public()
            self.assertNotIn('key',public['anki'])
            self.assertTrue(public['anki']['key_saved'])
            settings.save(public)
            self.assertEqual(settings.values['anki']['key'],'secret')
            restored=StatsSettings(directory)
            self.assertEqual(restored.values['gsm']['url'],draft['gsm']['url'])
            self.assertEqual(restored.values['anki']['decks'],['A','B::C'])
            self.assertEqual(restored.path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(ValueError):
                draft['gsm']['url']='file:///etc/passwd';settings.save(draft)
            self.assertEqual(StatsSettings(directory).values,restored.values)

    def test_disabled_sources_never_run_and_keep_recorded_data(self):
        with tempfile.TemporaryDirectory() as directory:
            settings=StatsSettings(directory)
            for source in settings.values.values():source['enabled']=False
            db=Path(directory)/'ledger.db';store=ReadingStats(db);store.record('test','日本語','Book');store.db.close()
            with patch('anki_stats.refresh_anki',side_effect=AssertionError('Disabled Anki called')), patch('stats_refresh.fetch_webdav',side_effect=AssertionError('Disabled WebDAV called')):
                self.assertEqual(refresh_configured(db,settings.values,directory),'No refresh sources enabled.')
            store=ReadingStats(db);self.assertEqual(store.summary()['total'],3);store.db.close()

    def test_stale_anki_job_cannot_replace_new_deck_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ReadingStats(Path(directory)/'stats.db')
            replace_reviews(store,[(1794492000000,'2026-11-12','New',2500)])
            store.set_preference('anki_config_version',config_version({'decks':['New']}))
            store.anki_configuration=config_version({'decks':['Old']})
            with self.assertRaises(ValueError):
                replace_reviews(store,[(1794492000001,'2026-11-12','Old',9000)])
            self.assertEqual(store.summary()['anki_seconds'],2.5)
            self.assertEqual(store.summary()['anki_decks'][0]['deck'],'New')
            store.db.close()

    def test_selected_subdeck_is_supported_for_collection_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'collection.anki2';collection(path)
            rows=collection_reviews(path,['Mining::Subdeck'])
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0][2],'Mining::Subdeck')


class ConnectTests(unittest.TestCase):
    def test_selected_decks_review_milliseconds_dedup_empty_and_failure(self):
        requests=[];mode=['normal']
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(req)
                action=req['action'];params=req['params']
                if action=='deckNames':result=['Parent','Parent::Child','Other']
                elif action=='findCards':result=[] if mode[0]=='empty' else ([1,2] if params['query']=='deck:"Parent"' else [2])
                elif action=='getReviewsOfCards':result={str(card):[{'id':1794492000000+card,'time':1000*card}] for card in params['cards']}
                else:result=None
                data={'result':result,'error':'bad key' if mode[0]=='error' else None}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                config={'backend':'connect','url':f'http://127.0.0.1:{server.server_port}','key':'secret','decks':['Parent','Parent::Child']}
                self.assertEqual(available_decks(config),['Other','Parent','Parent::Child'])
                store=ReadingStats(Path(directory)/'stats.db')
                for _ in range(2):import_connect_reviews(store,config)
                self.assertEqual(store.summary()['anki_seconds'],3)
                self.assertEqual(store.db.execute('SELECT deck FROM anki_reviews WHERE id=?',(1794492000002,)).fetchone()[0],'Parent::Child')
                self.assertTrue(all(r['key']=='secret' for r in requests))
                mode[0]='error'
                with self.assertRaises(ValueError):import_connect_reviews(store,config)
                self.assertEqual(store.summary()['anki_seconds'],3)
                mode[0]='empty';import_connect_reviews(store,config)
                self.assertEqual(store.summary()['anki_seconds'],0)
                store.db.close()
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
