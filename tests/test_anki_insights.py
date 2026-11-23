import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import date,datetime
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from anki_insights import load_insights,kanji_characters,target_deck,kanji_catalog,clean_kanji_preferences


def collection(path, *, updated=False):
    db=sqlite3.connect(path)
    db.executescript('''CREATE TABLE decks(id,name);CREATE TABLE cards(id,nid,did,odid,mod,type,queue,ivl,reps,lapses);
        CREATE TABLE notes(id,mid,flds);CREATE TABLE fields(ntid,ord,name);
        CREATE TABLE revlog(id,cid,ease,ivl,lastIvl,time,type);''')
    db.executemany('INSERT INTO decks VALUES (?,?)',[(1,'Parent'),(2,'Parent\x1fChild'),(3,'Other'),(4,'Filtered')])
    db.executemany('INSERT INTO fields VALUES (?,?,?)',[(1,0,'Expression'),(1,1,'Definition')])
    db.executemany('INSERT INTO notes VALUES (?,?,?)',[(1,1,'日本\x1f翻訳'),(2,1,'日本語\x1f説明'),(3,1,'除外\x1f説明'),(4,1,'山\x1f説明')])
    db.executemany('INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?)',[
        (1,1,1,0,2 if updated else 1,2,2,60 if updated else 30,10,1),
        (2,2,4,2,1,0,0,0,0,0),(3,3,3,0,1,2,2,100,10,1),(4,4,1,0,1,2,-1,10,5,1)])
    stamp=int(datetime(2026,11,12,12).timestamp()*1000)
    db.executemany('INSERT INTO revlog VALUES (?,?,?,?,?,?,?)',[
        (stamp,1,3,30,15,6000,1),(stamp+1,1,1,1,30,2000,1),
        (stamp+2,2,3,1,-60,1000,0),(stamp+3,3,3,100,60,99999,1),
        (stamp+4,1,0,60,30,99999,4)])
    if updated:db.execute('INSERT INTO revlog VALUES (?,?,?,?,?,?,?)',(stamp+5,1,4,60,30,1000,1))
    db.commit();db.close()

class AnkiInsightTests(unittest.TestCase):
    def config(self,paths):return {'enabled':True,'backend':'collection','decks':['Parent','Parent::Child'],'paths':paths}
    def load(self,config):return load_insights(config,today=date(2026,11,16),options={'fields':[],'interval':180})

    def test_selected_decks_filtered_cards_combined_counts_and_kanji_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'col.db';collection(path)
            data=self.load(self.config([str(path)]));combined=data['combined']
            self.assertEqual(combined['cards'],3)
            self.assertEqual(sum(combined['answers']),3)  # no other-deck or manual-reschedule logs
            self.assertEqual(combined['stages'],[1,0,0,1,1])
            self.assertEqual({c['char'] for c in combined['kanji']},set('日本語山'))
            self.assertEqual(combined['fields'],['Expression'])
            self.assertEqual([g['cards'] for g in data['decks']],[2,1])
            day=combined['days']['2026-11-12']
            self.assertEqual(day['retention_total'],2);self.assertEqual(day['retention_pass'],1)
            self.assertEqual(day['first'],2);self.assertEqual(day['seconds'],9)
            nihon=next(c for c in combined['kanji'] if c['char']=='日')
            self.assertEqual((nihon['seen'],nihon['unseen'],nihon['interval']),(1,1,30))

    def test_snapshots_union_reviews_and_choose_newest_card_state(self):
        with tempfile.TemporaryDirectory() as directory:
            first=Path(directory)/'old.db';second=Path(directory)/'new.db'
            collection(first);collection(second,updated=True)
            for paths in ([str(first),str(second)],[str(second),str(first)]):
                combined=self.load(self.config(paths))['combined']
                self.assertEqual(sum(combined['answers']),4)
                self.assertEqual(next(c for c in combined['kanji'] if c['char']=='日')['interval'],60)

    def test_joyo_catalog_full_unique_with_official_forms(self):
        catalog=kanji_catalog()
        self.assertEqual(len(catalog['joyo']),2136)
        self.assertEqual(len(set(catalog['joyo'])),2136)
        self.assertTrue(set('剝頰塡𠮟')<=set(catalog['joyo']))
        self.assertIn('grade',catalog['groups']);self.assertIn('jlpt',catalog['groups'])

    def test_kanji_options_validation_and_fields_are_independent(self):
        options=clean_kanji_preferences({'fields':['Expression','Sentence'],'interval':90,'tile_size':40,'group':'grade','palette':'kanjigrid','show_missing':False})
        self.assertEqual(options['fields'],['expression','sentence'])
        self.assertEqual(options['interval'],90)
        self.assertTrue(options['show_unseen'])
        for bad in ({'tile_size':1},{'interval':0},{'fields':'Expression'},{'group':'unknown'},{'palette':'url(x)'},{'show_missing':'false'}):
            with self.assertRaises(ValueError):clean_kanji_preferences(bad)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'col.db';collection(path)
            data=load_insights(self.config([str(path)]),options=options)
            self.assertEqual(data['options']['interval'],90)
            self.assertIn('Definition',data['available_fields'])
            self.assertEqual(data['combined']['fields'],['Expression'])

    def test_deck_view_modes_and_persisted_selection_validation(self):
        self.assertEqual(clean_kanji_preferences({})['deck'],'combined')
        for group in ('none','grade','jlpt','decks'):
            preferences=clean_kanji_preferences({'group':group,'deck':'deck:Mining'})
            self.assertEqual(preferences['group'],group)
            self.assertEqual(preferences['deck'],'deck:Mining')
            self.assertEqual(clean_kanji_preferences({},preferences),preferences)
        for invalid in (None,False,12,'Mining',''):
            with self.assertRaises(ValueError):clean_kanji_preferences({'deck':invalid})

    def test_read_only_and_missing_source_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'col.db';collection(path)
            before=path.read_bytes();self.load(self.config([str(path),str(path)+'missing']))
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(ValueError):self.load(self.config([str(path)+'missing']))

    def test_html_furigana_and_definition_kanji_are_not_included(self):
        self.assertEqual(kanji_characters('<ruby>山<rt>訓読</rt></ruby><img src="外.png"><script>危険</script>[sound:音声.mp3]'),{'山'})
        self.assertEqual(target_deck('Parent\x1fChild',['Parent','Parent::Child']),'Parent::Child')

    def test_connect_uses_same_deck_rules_and_deduplicates_overlap(self):
        stamp=int(datetime(2026,11,12,12).timestamp()*1000)
        def request(config,action,**params):
            if action=='findCards':return [1] if 'Child' in params['query'] else [1,2]
            if action=='cardsInfo':return [{'cardId':cid,'note':cid,'fields':{'Expression':{'value':'日本','order':0},'Definition':{'value':'除外','order':1}},'type':2,'queue':2,'interval':30} for cid in params['cards']]
            if action=='getReviewsOfCards':return {str(cid):[{'id':stamp+cid,'ease':3,'ivl':30,'lastIvl':15,'time':1000,'type':1}] for cid in params['cards']}
            raise AssertionError(action)
        config=self.config([]);config['backend']='connect'
        with patch('anki_insights.anki_request',side_effect=request):data=self.load(config)
        self.assertEqual(data['combined']['cards'],2)
        self.assertEqual([g['cards'] for g in data['decks']],[1,1])
        self.assertEqual(sum(data['combined']['answers']),2)
        self.assertEqual({c['char'] for c in data['combined']['kanji']},set('日本'))

if __name__=='__main__':unittest.main()
