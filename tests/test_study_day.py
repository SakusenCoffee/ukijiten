import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime,date
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from reading_stats import ReadingStats
from anki_stats import replace_reviews
from anki_insights import load_insights
from stats_settings import StatsSettings
from study_day import study_date,validate_cutoff
from test_anki_insights import collection

class StudyDayTests(unittest.TestCase):
    def setUp(self):
        self.old_zone=os.environ.get('TZ');os.environ['TZ']='America/Chicago';time.tzset()
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=ReadingStats(self.root/'stats.db')
    def tearDown(self):
        self.store.db.close();self.temp.cleanup()
        if self.old_zone is None:os.environ.pop('TZ',None)
        else:os.environ['TZ']=self.old_zone
        time.tzset()
    def test_midnight_capture_and_reversible_daily_grouping_preserve_totals(self):
        self.store.set_preference('day_cutoff_hour',4)
        self.store.record('a','日本','Book','2026-11-12T23:59:50-06:00')
        self.store.record('b','語','Book','2026-11-13T00:00:10-06:00')
        raw=self.store.db.execute('SELECT * FROM readings ORDER BY key').fetchall()
        with patch('study_day.datetime') as clock:
            clock.now.return_value=datetime.fromisoformat('2026-11-13T01:00:00-06:00')
            before=self.store.summary()
        self.assertEqual(before['today_day'],'2026-11-12');self.assertEqual(before['today'],3)
        self.assertEqual(before['days']['2026-11-12']['characters'],3)
        self.assertEqual(before['seconds'],20)
        self.assertEqual(before['recent'][0]['day'],'2026-11-12')
        self.store.set_preference('day_cutoff_hour',0);after=self.store.summary()
        self.assertEqual(after['days']['2026-11-13']['characters'],1)
        self.assertEqual((before['total'],before['seconds']),(after['total'],after['seconds']))
        self.assertEqual(raw,self.store.db.execute('SELECT * FROM readings ORDER BY key').fetchall())
        self.store.set_preference('day_cutoff_hour',4)
        reopened=ReadingStats(self.root/'stats.db')
        self.assertEqual(reopened.day_cutoff_hour(),4);reopened.db.close()
    def test_anki_heatmap_and_cutoff_boundary(self):
        one=int(datetime.fromisoformat('2026-11-13T01:00:00-06:00').timestamp()*1000)
        four=int(datetime.fromisoformat('2026-11-13T04:00:00-06:00').timestamp()*1000)
        rows=[(one,'2026-11-13','Deck',1000),(four,'2026-11-13','Deck',2000)]
        replace_reviews(self.store,rows);self.store.set_preference('day_cutoff_hour',4)
        stats=self.store.summary()
        self.assertEqual(stats['anki_days']['2026-11-12']['reviews'],1)
        self.assertEqual(stats['anki_days']['2026-11-13']['reviews'],1)
        self.assertEqual(stats['anki_seconds'],3)
        self.assertEqual({row[0] for row in self.store.db.execute('SELECT day FROM anki_reviews')},{'2026-11-13'})
        replace_reviews(self.store,rows)
        self.assertEqual(self.store.summary()['anki_days'],stats['anki_days'])
    def test_daily_imports_and_explicit_manual_dates_remain_dates(self):
        self.store.set_preference('day_cutoff_hour',4)
        path=self.root/'daily.csv';path.write_text('Date,Characters\n2026-11-13,10\n')
        self.store.import_file(path);self.store.add_manual_entry(5,0,1,'Manual','2026-11-13')
        self.assertEqual(self.store.summary()['days']['2026-11-13']['characters'],15)
    def test_daylight_saving_uses_wall_clock_cutoff(self):
        for index,stamp in enumerate(('2026-11-01T01:30:00-05:00','2026-11-01T01:30:00-06:00','2026-11-01T04:00:00-06:00')):
            self.store.record(str(index),'字','Book',stamp)
        self.store.set_preference('day_cutoff_hour',4)
        stats=self.store.summary()
        self.assertEqual(stats['days']['2026-10-31']['characters'],2)
        self.assertEqual(stats['days']['2026-11-01']['characters'],1)
        self.assertEqual(study_date(datetime.fromisoformat('2026-11-01T04:00:00-06:00'),4),date(2026,11,1))
    def test_settings_validation_and_persistence(self):
        settings=StatsSettings(self.root/'config');draft=settings.public()
        self.assertEqual(draft['day']['cutoff_hour'],0)
        draft['day']['cutoff_hour']=4;settings.save(draft)
        self.assertEqual(StatsSettings(self.root/'config').values['day']['cutoff_hour'],4)
        for value in (-1,24,2.5,True,'4',None):
            with self.assertRaises(ValueError):validate_cutoff(value)
            draft['day']['cutoff_hour']=value
            with self.assertRaises(ValueError):settings.save(draft)
        self.assertEqual(StatsSettings(self.root/'config').values['day']['cutoff_hour'],4)
    def test_daily_anki_graphs_use_the_same_cutoff(self):
        path=self.root/'collection.db';collection(path)
        db=sqlite3.connect(path);old=db.execute('SELECT MIN(id) FROM revlog').fetchone()[0]
        early=int(datetime.fromisoformat('2026-11-12T01:00:00-06:00').timestamp()*1000)
        db.execute('UPDATE revlog SET id=? WHERE id=?',(early,old));db.commit();db.close()
        config={'enabled':True,'backend':'collection','decks':['Parent'],'paths':[str(path)]}
        data=load_insights(config,today=date(2026,11,16),cutoff_hour=4)
        self.assertEqual(data['combined']['days']['2026-11-11']['reviews'],1)
        self.assertEqual(data['combined']['hourly'][1],1)

if __name__=='__main__':unittest.main()
