"""Persistent history of completed search-bar lookups."""
import sqlite3
import time


class SearchHistory:
    def __init__(self, path):
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS searches(query TEXT PRIMARY KEY,headword TEXT NOT NULL,searched INTEGER NOT NULL)')

    def add(self, query, headword):
        query=query.strip()
        if not query or len(query)>512:return
        with self.db:self.db.execute('INSERT OR REPLACE INTO searches VALUES (?,?,?)',(query,headword or query,time.time_ns()))

    def entries(self, oldest=False):
        order='ASC' if oldest else 'DESC'
        return [dict(query=q,headword=h,searched=t/1e6) for q,h,t in self.db.execute(f'SELECT query,headword,searched FROM searches ORDER BY searched {order},query')]

    def close(self):
        self.db.close()
