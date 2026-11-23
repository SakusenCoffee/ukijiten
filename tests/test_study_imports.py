import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reading_stats import ReadingStats
from import_assets import import_path,list_assets,remove
from stats_settings import StatsSettings
from anki_stats import replace_reviews


class StudyImportsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=ReadingStats(self.root/'stats.db')

    def tearDown(self):
        self.store.db.close();self.temp.cleanup()

    def upload(self,name,data,kind):
        path=self.root/name;path.write_text(json.dumps(data));import_path(self.store,path,kind)
        return path

    def test_jpdb_overlap_removal_and_anki_filter_preserve_raw_events(self):
        data={'cards_vocabulary_jp_en':[{'vid':1,'spelling':'本','reading':'ほん','reviews':[
            {'timestamp':1794492000,'grade':'good','from_anki':False},
            {'timestamp':1794492001,'grade':'good','from_anki':True}]}]}
        path=self.upload('jpdb.json',data,'jpdb');self.upload('copy.json',data,'jpdb')
        self.assertEqual(self.store.summary()['study_sources']['jpdb']['reviews'],1)
        self.assertEqual(self.store.summary()['total'],0);self.assertEqual(self.store.summary()['seconds'],0)
        self.store.set_preference('source_metrics',{'jpdb':{'include_anki_reviews':True}})
        self.assertEqual(self.store.summary()['study_sources']['jpdb']['reviews'],2)
        identifier=next(a['id'] for a in list_assets(self.store) if a['path']==str(path))
        remove(self.store,identifier)
        self.assertEqual(self.store.summary()['study_sources']['jpdb']['reviews'],2)
        self.store.set_preference('source_metrics',{'jpdb':{'include_activity':False}})
        self.assertNotIn('jpdb',self.store.summary()['study_sources'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM study_activity').fetchone()[0],2)
        remove(self.store,list_assets(self.store)[0]['id'])
        self.assertFalse(self.store.summary()['study_sources'])

    def test_renshuu_is_goal_percentage_without_invented_review_counts(self):
        path=self.upload('renshuu.json',{'heatmap':{'Week 1':{'11/12/26':78,'11/13/26':0,'11/14/26':'scheduled holiday'}}},'renshuu')
        result=self.store.summary()['study_sources']['renshuu']
        self.assertEqual(result['reviews'],0)
        self.assertEqual(result['days']['2026-11-12']['completion'],78)
        self.assertEqual(len(result['days']),2)
        path.write_text('{}')
        with self.assertRaises(ValueError):import_path(self.store,path,'renshuu')
        self.assertEqual(self.store.summary()['study_sources']['renshuu'],result)

    def test_updated_ttsu_exports_replace_days_and_metric_filters_are_reversible(self):
        rows=[{'title':'Book','dateKey':'2026-11-01','charactersRead':100,'readingTime':125}]
        old=self.upload('old.json',rows,'ttsu');os.utime(old,(100,100))
        import_path(self.store,old,'ttsu')
        rows[0].update(charactersRead=150,readingTime=200)
        newer=self.upload('new.json',rows,'ttsu')
        self.assertEqual(self.store.summary()['total'],150);self.assertEqual(self.store.summary()['seconds'],200)
        import_path(self.store,old,'ttsu')
        self.assertEqual(self.store.summary()['total'],150)
        raw=self.store.db.execute('SELECT * FROM readings').fetchall()
        self.store.set_preference('source_metrics',{'ttsu':{'include_time':False,'include_characters':True}})
        self.assertEqual(self.store.summary()['total'],150);self.assertEqual(self.store.summary()['seconds'],0)
        self.store.set_preference('source_metrics',{'ttsu':{'include_time':True,'include_characters':False}})
        self.assertEqual(self.store.summary()['total'],0);self.assertEqual(self.store.summary()['seconds'],200)
        self.assertEqual(self.store.db.execute('SELECT * FROM readings').fetchall(),raw)
        self.store.set_preference('source_metrics',{})
        remove(self.store,next(a['id'] for a in list_assets(self.store) if a['path']==str(newer)))
        self.assertEqual(self.store.summary()['total'],100);self.assertAlmostEqual(self.store.summary()['seconds'],125)

    def test_api_key_private_and_filters_persist(self):
        settings=StatsSettings(self.root);draft=settings.public()
        draft['renshuu']['key']='test-private-key';draft['ttsu']['include_time']=False
        settings.save(draft)
        public=settings.public();self.assertNotIn('key',public['renshuu']);self.assertTrue(public['renshuu']['key_saved'])
        settings.save(public)
        restored=StatsSettings(self.root)
        self.assertEqual(restored.values['renshuu']['key'],'test-private-key')
        self.assertFalse(restored.values['ttsu']['include_time'])

    def test_anki_time_can_be_excluded_without_removing_reviews(self):
        replace_reviews(self.store,[(1794492000000,'2026-11-12','Deck',2500)])
        self.store.set_preference('source_metrics',{'anki':{'include_time':False}})
        result=self.store.summary()
        self.assertEqual(result['anki_seconds'],0)
        self.assertEqual(result['anki_days']['2026-11-12']['reviews'],1)
        self.assertEqual(result['anki_decks'][0]['reviews'],1)
        self.store.set_preference('source_metrics',{})
        self.assertEqual(self.store.summary()['anki_seconds'],2.5)


if __name__=='__main__':unittest.main()
