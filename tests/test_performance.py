import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from threading import Event
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from media_catalog import MediaCatalog
from yomitan_goldendict import search_entries, search_patterns
from async_lookup import AsyncLookup, lookup


_application = None

def qt_app():
    global _application
    _application = QCoreApplication.instance() or QCoreApplication([])
    return _application


def database(path=':memory:'):
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE dictionaries(id INTEGER PRIMARY KEY,title TEXT,enabled INTEGER,sort_order INTEGER);
    CREATE TABLE entries(dictionary_id INTEGER,term TEXT,reading TEXT,glossary TEXT);
    CREATE INDEX entries_term ON entries(term);
    CREATE INDEX entries_reading ON entries(reading);''')
    db.executemany('INSERT INTO dictionaries VALUES(?,?,?,?)', [(1,'First',1,2),(2,'Second',1,1),(3,'Disabled',0,0)])
    for did in (1,2,3):
        db.executemany('INSERT INTO entries VALUES(?,?,?,?)', [(did,t,r,'["definition"]') for t,r in
            [('先生','せんせい'),('先','さき'),('先生方','せんせいがた'),('先制','せんせい'),
             ('a*b',''),('a?b',''),('[abc]',''),('100%',''),('x_y','')]+[(f'先生{i:03d}','せんせい') for i in range(70)]])
    db.commit()
    return db


class SearchTests(unittest.TestCase):
    def setUp(self): self.db=database()
    def tearDown(self): self.db.close()
    def test_ranking_limit_and_order(self):
        rows=search_entries(self.db,'先')
        self.assertEqual(len(rows),80)
        self.assertEqual([r[3] for r in rows], [2]*40+[1]*40)
        self.assertEqual(rows[0][0],'先')
        self.assertEqual(search_entries(self.db,'sensei'),search_entries(self.db,'せんせい'))
    def test_wildcards_and_literal_escaping(self):
        self.assertEqual({r[0] for r in search_entries(self.db,'先?')},{'先生','先制'})
        self.assertEqual({r[0] for r in search_entries(self.db,'*方')},{'先生方'})
        self.assertEqual({r[0] for r in search_entries(self.db,r'a\*b')},{'a*b'})
        self.assertEqual({r[0] for r in search_entries(self.db,r'a\?b')},{'a?b'})
        self.assertEqual({r[0] for r in search_entries(self.db,'[abc]')},{'[abc]'})
        self.assertEqual(search_entries(self.db,'   '),[])
        self.assertEqual(search_entries(self.db,"'; DROP TABLE entries;--"),[])
    def test_database_enable_order_changes_take_effect(self):
        self.db.execute('UPDATE dictionaries SET enabled=0 WHERE id=2')
        self.assertEqual({r[3] for r in search_entries(self.db,'先')},{1})
    def test_prefix_uses_indexes(self):
        plan=self.db.execute('EXPLAIN QUERY PLAN SELECT rowid FROM entries WHERE term GLOB ?',('先*',)).fetchall()
        self.assertIn('SEARCH entries USING COVERING INDEX entries_term',str(plan))
    def test_cancel_before_start(self):
        event=Event();event.set()
        self.assertEqual(lookup('test',event),[])


class HoverTests(unittest.TestCase):
    def test_shared_index_enabled_state_and_longest_match(self):
        import json
        from hover_lookup import hover_lookup
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'dict.sqlite';db=database(path)
            payload=json.dumps([{'text':'先','length':1},{'text':'先生','length':2}])
            rows=hover_lookup(payload,Event(),path)
            self.assertEqual({r[0] for r in rows},{'先生'})
            self.assertEqual([r[3] for r in rows],[2,1])
            db.execute('UPDATE dictionaries SET enabled=0 WHERE id=2');db.commit()
            self.assertEqual({r[3] for r in hover_lookup(payload,Event(),path)},{1})
            db.close()


class PopupSettingsTests(unittest.TestCase):
    def test_independent_selection_and_persistence(self):
        from popup_settings import PopupSettings
        dictionaries=[(1,'A','a.zip',1),(2,'B','b.zip',0)]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            settings=PopupSettings(path,dictionaries)
            self.assertEqual(settings.enabled_ids(dictionaries),[1])
            settings.update('dictionary',{'path':'b.zip','enabled':True})
            settings.update('dictionary',{'path':'a.zip','enabled':False})
            self.assertEqual(settings.enabled_ids(dictionaries),[2])
            self.assertEqual(PopupSettings(path,dictionaries).enabled_ids(dictionaries),[2])
            self.assertEqual(dictionaries[0][3],1)
    def test_hover_order_and_hotkey_migration(self):
        import json
        from popup_settings import PopupSettings
        from hover_lookup import hover_lookup
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            path.write_text(json.dumps({'shift_required':True}))
            dictionaries=[(1,'A','a.zip',1),(2,'B','b.zip',1)]
            settings=PopupSettings(path,dictionaries)
            self.assertEqual(settings.values['scan_hotkey'],['Shift'])
            settings.update('dictionary_order',['b.zip','a.zip'])
            settings.update('scan_hotkey',['Control','KeyD'])
            self.assertEqual(settings.enabled_ids(dictionaries),[2,1])
            self.assertEqual(PopupSettings(path,dictionaries).values['scan_hotkey'],['Control','KeyD'])
            dbpath=Path(directory)/'test.sqlite';db=database(dbpath)
            rows=hover_lookup(json.dumps([{'text':'先生','length':2}]),Event(),dbpath,enabled_ids=[1,2])
            self.assertEqual([r[3] for r in rows],[1,2])
            self.assertEqual(db.execute('SELECT id FROM dictionaries WHERE enabled=1 ORDER BY sort_order').fetchall(),[(2,),(1,)])
            db.close()
    def test_hover_can_use_main_disabled_dictionary(self):
        import json
        from hover_lookup import hover_lookup
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'db.sqlite';database(path).close()
            payload=json.dumps([{'text':'先生','length':2}])
            self.assertEqual({r[3] for r in hover_lookup(payload,Event(),path,enabled_ids=[3])},{3})
            self.assertEqual(hover_lookup(payload,Event(),path,enabled_ids=[]),[])


class FolderTests(unittest.TestCase):
    def test_cache_invalidation_no_image_decode_and_independent_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'a.GIF').write_bytes(b'invalid')
            (folder/'b.txt').write_text('not an image')
            catalog=MediaCatalog()
            with patch('media_catalog.QImageReader') as reader:
                first=catalog.files(folder)
                self.assertEqual(len(first),1)
                first.reverse();first.clear()
                self.assertEqual(len(catalog.files(folder)),1)
                (folder/'c.png').write_bytes(b'also invalid')
                self.assertEqual(len(catalog.files(folder)),2)
                reader.assert_not_called()
            self.assertFalse(catalog.readable(str(folder/'a.GIF')))


class AsyncTests(unittest.TestCase):
    def test_metadata_runs_off_ui_thread_and_latest_selection_wins(self):
        from threading import get_ident
        from entry_metadata import MetadataResults
        app=qt_app();owner=AsyncLookup(None)
        started=Event();threads=[];received=[];main_thread=get_ident()
        class Cache:
            def enrich(self,entries,selection,cancelled):
                threads.append(get_ident())
                if entries[0][0]=='old':
                    started.set();cancelled.wait(1)
                return MetadataResults(entries,{'selection':selection})
        owner.metadata_cache=Cache()
        selection=(('first.zip',),())
        owner.metadata_selection_provider=lambda:selection
        owner.ready.connect(lambda query,rows,error:received.append((query,rows,error)))
        try:
            with patch('async_lookup.lookup',lambda query,cancelled:[(query, '', '["definition"]', 1, 'Test')]):
                owner.submit('old')
                self.assertTrue(started.wait(1))
                selection=(('first.zip','second.zip'),())
                owner.submit('new')
                deadline=time.monotonic()+2
                while not received and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.005)
                self.assertEqual(len(received),1)
                self.assertEqual(received[0][0],'new')
                self.assertEqual(received[0][1].metadata,{'selection':selection})
                self.assertTrue(all(thread!=main_thread for thread in threads))
        finally:owner.shutdown()

    def test_latest_request_only_and_cancel_navigation(self):
        app=qt_app()
        owner=AsyncLookup(None)
        received=[]
        owner.ready.connect(lambda q,rows,error:received.append((q,rows,error)))
        def slow(query,cancelled):
            if query=='old': cancelled.wait(.5)
            return [(query, '', '["definition"]', 1, 'Test')]
        try:
            with patch('async_lookup.lookup',slow):
                owner.submit('old');owner.submit('new')
                deadline=time.monotonic()+2
                while not received and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.005)
                self.assertEqual(received,[('new', [('new', '', '["definition"]', 1, 'Test')], '')])
                owner.submit('old');owner.cancel()
                for _ in range(10):app.processEvents();time.sleep(.005)
                self.assertEqual(len(received),1)
        finally:owner.shutdown()


if __name__=='__main__': unittest.main()
