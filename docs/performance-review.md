# Performance review

## Search

The existing SQLite term and reading indexes are appropriate. Search keeps its
current romaji variants, wildcard rules, ranking, dictionary order and 40-result
limit per dictionary. Popup search keeps its independent source selection and
longest-match behavior.

Changes:

- Cache recent result rows across panes, bounded by 128 entries and approximately
  16 MiB of Python row/string storage. Database, WAL and journal changes invalidate
  keys, including imports and source enable/order changes.
- Prepare definitions in lookup workers. Cache rendered definitions separately,
  bounded by 512 entries and approximately 8 MiB of string storage.
- Deliver completion through queued Qt signals instead of 25 ms polling for main
  searches and 8 ms polling for popup searches. Stale results remain discarded.
- Fetch popup definitions in one batch and read metadata-source flags in one query.

Measurements on a 4.81-million-entry collection (five repetitions, warm OS cache):

| Query | Result rows | Direct SQL median | Result-cache median |
| --- | ---: | ---: | ---: |
| 先生 | 31 | 0.234 ms | 0.024 ms |
| sensei | 112 | 0.500 ms | 0.025 ms |
| 懐 | 248 | 1.941 ms | 0.024 ms |
| hara | 262 | 3.819 ms | 0.023 ms |
| あ | 320 | 109.201 ms | 0.025 ms |
| *先生 | 69 | 446.260 ms | 0.023 ms |
| 先? | 280 | 2.989 ms | 0.023 ms |

These are backend lookup times, not keystroke-to-paint measurements. They exclude
metadata enrichment, rendering, and the unchanged 180 ms typing debounce. First
lookups still depend on disk/cache state. Leading wildcards still scan indexes.

Covering indexes and an alternative per-dictionary top-K query were tested on a
separate database copy. Neither justified replacing the existing query. No search
schema migration or new indexes were retained.

Reproduce with:

```sh
python tools/benchmark_lookup.py /path/to/dictionaries.sqlite3
```

## Background work

AnkiConnect previously fetched every selected card's full review history every
30 seconds. A measured 97,569-review import took 18–20 seconds. An unchanged local
refresh now checks the active profile and collection/WAL/journal signatures;
the measured repeat took 27 ms. Reviews still come from AnkiConnect. Changed
collections and settings trigger a full refresh. Remote or unverifiable sources
retain the previous refresh behavior. Manual Refresh still performs a full fetch.

Background images rotate at the configured interval. Rendering, transparency and
animation settings were retained. Existing image-scaling and metadata caches were
already present and remain in use. Stats updates only render when the stats view
exists. Focus checks update the page only when focus changes.

## Structure and cleanup

- `dictionary_search.py`: query normalization and SQL search, without Qt imports.
- `dictionary_database.py`: paths and schema initialization.
- `dictionary_render.py`: restricted HTML rendering and definition caching.
- `image_panes.py`: avatar/background painting and interaction, extracted unchanged.
- `lookup_cache.py`: bounded worker-safe caches and database signatures.
- `anki_change_monitor.py`: local change detection for scheduled Anki refreshes.
- `tools/benchmark_lookup.py`: repeatable read-only performance check.

The dictionary manager retains compatibility exports. Launchers, asset paths,
configuration locations and user databases are unchanged. Removed unused imports
from extracted code and closed two short-lived SQLite readers explicitly.

The main window still coordinates many features. Further splitting its settings,
statistics and popup controllers is possible, but is not needed for the measured
improvements. A blanket directory move would add path/import churn without a
runtime benefit. Existing frontend modules and test layout are retained.

## Comparison

[Yomitan's database](https://github.com/yomidevs/yomitan/blob/master/ext/js/dictionary/dictionary-database.js)
uses indexed expression/reading lookups, bulk requests and bounded prefix ranges.
Its [translator](https://github.com/yomidevs/yomitan/blob/master/ext/js/language/translator.js)
groups deinflection candidates before database lookup and caches supporting data.
[GoldenDict](https://github.com/goldendict/goldendict/blob/master/btreeidx.cc)
uses B-tree exact/prefix lookup and cancellable worker requests.

Ukijiten uses the same basic indexed/off-thread strategy. This review does not
establish that it is faster than either application: they were not benchmarked
with identical dictionaries and workloads. Adding new deinflection rules, fuzzy
search or full-text search would change functionality and is outside this pass.

## Validation

- 157 unit tests passed, including new cache bounds, WAL invalidation, mutation
  isolation, render parity, and Anki change-monitor tests.
- Full floating-window UI smoke test passed, including dictionary, statistics,
  popup and appearance flows.
- Byte-for-byte result-list equality checked for the benchmark queries.
- Python compilation and whitespace checks passed.
- Existing unrelated local edits were preserved. No commit or push performed.
