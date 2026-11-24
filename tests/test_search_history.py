import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from search_history import SearchHistory


class SearchHistoryTests(unittest.TestCase):
    def test_order_repeated_search_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.sqlite3';history=SearchHistory(path)
            for stamp,query,headword in [(1,'sensei','先生'),(2,'先','先'),(3,'sensei','先生')]:
                with patch('search_history.time.time_ns',return_value=stamp):history.add(query,headword)
            self.assertEqual([r['query'] for r in history.entries()],['sensei','先'])
            self.assertEqual([r['query'] for r in history.entries(True)],['先','sensei'])
            history.add('  ','');history.close();history=SearchHistory(path)
            self.assertEqual(len(history.entries()),2)
            self.assertEqual(history.entries()[0]['headword'],'先生');history.close()

    def test_untrusted_query_remains_data(self):
        with tempfile.TemporaryDirectory() as folder:
            history=SearchHistory(Path(folder)/'history.sqlite3')
            query="'; DROP TABLE searches;--";history.add(query,'<img src=x>')
            self.assertEqual(history.entries()[0]['query'],query)
            history.add('先','先');self.assertEqual(len(history.entries()),2);history.close()
