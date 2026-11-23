import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
import sqlite3
import unittest
from pitch_accent import PitchAccents,parse_accents,morae,high


def glossary(signature):
    return json.dumps([{'type':'structured-content','content':{'tag':'span','data':{'pitchAccentText':'true','accentSig':signature}}}])


class PitchTests(unittest.TestCase):
    def test_morae_and_accent_patterns(self):
        self.assertEqual(morae('ギャップ'),['ギャ','ッ','プ'])
        self.assertEqual(parse_accents(glossary('セ＼ーブ')),[(('セ','ー','ブ'),1)])
        self.assertEqual(parse_accents(glossary('ガッコー━')),[(('ガ','ッ','コ','ー'),0)])
        self.assertEqual(parse_accents(glossary('ハシ＼')),[(('ハ','シ'),2)])
        self.assertEqual([high(i,0) for i in range(4)],[False,True,True,True])
        self.assertEqual([high(i,2) for i in range(3)],[False,True,False])
        self.assertEqual(parse_accents(glossary('ニホ＼ン | ニッポ＼ン')),[ (('ニ','ホ','ン'),2),(('ニ','ッ','ポ','ン'),3)])

    def test_disabled_nhk_used_and_reading_disambiguated(self):
        db=sqlite3.connect(':memory:')
        db.executescript('CREATE TABLE dictionaries(id,title,enabled);CREATE TABLE entries(dictionary_id,term,reading,glossary);CREATE INDEX entries_term ON entries(term);')
        db.execute("INSERT INTO dictionaries VALUES (1,'NHK-pitch',0)")
        db.executemany('INSERT INTO entries VALUES (?,?,?,?)',[(1,'先','せん',glossary('セ＼ン')),(1,'先','さき',glossary('サキ━'))])
        pitch=PitchAccents(db)
        result=pitch.rows([('先','せん'),('先','さき'),('先','さっき')])
        self.assertIn('[1]',result[('先','せん')]);self.assertNotIn('[0]',result[('先','せん')])
        self.assertIn('[0]',result[('先','さき')]);self.assertNotIn('[1]',result[('先','さき')])
        self.assertIn('No matching NHK pitch data',result[('先','さっき')])
        self.assertEqual(db.execute('SELECT enabled FROM dictionaries').fetchone()[0],0)
        self.assertIn('pitch-graph',result[('先','せん')])
        db.close()
