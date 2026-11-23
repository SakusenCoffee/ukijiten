import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sqlite3
import tempfile
import unittest
from anki_stats import collection_reviews,import_review_time
from reading_stats import ReadingStats


def collection(path,extra=False):
    db=sqlite3.connect(path)
    db.executescript('CREATE TABLE decks(id,name);CREATE TABLE cards(id,did,odid);CREATE TABLE revlog(id,cid,time);')
    db.executemany('INSERT INTO decks VALUES (?,?)',[(1,'Kaishi 1.5k'),(2,'Mining'),(3,'Mining\x1fSubdeck'),(4,'Other'),(5,'Filtered')])
    db.executemany('INSERT INTO cards VALUES (?,?,?)',[(1,1,0),(2,2,0),(3,3,0),(4,4,0),(5,5,2)])
    db.executemany('INSERT INTO revlog VALUES (?,?,?)',[(1794492000000,1,1000),(1794492000001,2,2000),(1794492000002,3,3000),(1794492000003,4,999999),(1794492000004,5,4000)])
    if extra:db.execute('INSERT INTO revlog VALUES (?,?,?)',(1794492000005,2,5000))
    db.commit();db.close()


class AnkiTimeTests(unittest.TestCase):
    def test_deck_filter_subdecks_and_original_filtered_deck(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'collection.db';collection(path)
            rows=collection_reviews(path)
            self.assertEqual(len(rows),4)
            self.assertEqual(sum(row[3] for row in rows),10000)
            self.assertEqual({row[2] for row in rows},{'Kaishi 1.5k','Mining'})

    def test_freshest_source_idempotent_and_no_invented_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);local=root/'local.db';server=root/'server.db'
            collection(local);collection(server,extra=True)
            store=ReadingStats(root/'stats.db')
            store.record('reading','日本語','Book')
            for _ in range(2):import_review_time(store,[local,server])
            stats=store.summary()
            self.assertEqual(stats['total'],3)
            self.assertEqual(stats['anki_seconds'],15)
            self.assertEqual(stats['seconds'],15)
            self.assertEqual(sum(deck['reviews'] for deck in stats['anki_decks']),5)
            self.assertEqual(stats['active_days'],1)
            self.assertEqual(sum(day['reviews'] for day in stats['anki_days'].values()),5)
            self.assertEqual(sum(day['characters'] for day in stats['consistency_days'].values()),3)
            store.db.close()

    def test_missing_server_falls_back_to_local(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);local=root/'local.db';collection(local)
            store=ReadingStats(root/'stats.db')
            result=import_review_time(store,[root/'missing.db',local])
            self.assertEqual(result['source'],str(local))
            self.assertEqual(store.summary()['anki_seconds'],10)
            store.db.close()

    def test_unsynced_reviews_from_both_devices_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);local=root/'local.db';server=root/'server.db'
            collection(local);collection(server,extra=True)
            db=sqlite3.connect(local)
            db.execute('INSERT INTO revlog VALUES (?,?,?)',(1794492000006,1,6000));db.commit();db.close()
            store=ReadingStats(root/'stats.db')
            import_review_time(store,[local,server])
            self.assertEqual(store.summary()['anki_seconds'],21)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM anki_reviews').fetchone()[0],6)
            store.db.close()
