"""Read-only lookup benchmark. Run with an existing dictionary database."""
import argparse
from pathlib import Path
import sqlite3
import statistics
import sys
from threading import Event
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from async_lookup import lookup
from dictionary_search import search_entries


def measure(call, repeats):
    times = []
    for _ in range(repeats):
        start = perf_counter()
        result = call()
        times.append((perf_counter() - start) * 1000)
    return result, statistics.median(times)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--queries', nargs='+', default=['先生', 'sensei', '懐', 'hara', 'あ', '*先生', '先?'])
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    path = args.database.expanduser().resolve()
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        print('query\trows\tSQL median ms\tcached median ms')
        for query in args.queries:
            expected, direct = measure(lambda: search_entries(db, query), args.repeats)
            # Prime the process cache separately; no OS cache flushing or DB writes.
            lookup(query, Event(), path)
            actual, cached = measure(lambda: lookup(query, Event(), path), args.repeats)
            if actual != expected:
                raise AssertionError(f'Results changed for {query!r}')
            print(f'{query}\t{len(actual)}\t{direct:.3f}\t{cached:.3f}', flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
