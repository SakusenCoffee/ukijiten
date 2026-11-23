"""Read-only source adapters for importing existing GSM and Mokuro history."""
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from reading_stats import ReadingStats, gsm_line_key, local_timestamp,japanese_characters
from study_day import study_date


def import_gsm(store, path):
    source = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    try:
        rows = source.execute('''SELECT l.*,g.obs_scene_name,g.title_original,g.title_romaji FROM game_lines l
            LEFT JOIN games g ON l.game_id=g.id ORDER BY l.timestamp,l.id''').fetchall()
        durations = {(r['date'], r['game_id']): float(r['total_reading_time_seconds'] or 0)
            for r in source.execute('SELECT * FROM game_daily_rollup')}
    finally:
        source.close()
    changed = 0
    groups = defaultdict(list)
    original_characters=defaultdict(int)
    with store.db:
        store.batching = True
        try:
            for row in rows:
                if row['language'] not in ('ja', 'jp', 'Japanese', 'ja-JP', '', None):
                    continue
                stamp = datetime.fromtimestamp(float(row['timestamp']), timezone.utc)
                label = row['game_name'] or row['obs_scene_name'] or row['title_original'] or row['title_romaji'] or 'GSM'
                key = gsm_line_key(row['id'])
                changed += bool(store.record(key, row['line_text'] or '', label, stamp.isoformat()))
                groups[(stamp.astimezone().date().isoformat(), row['game_id'])].append(key)
                original_characters[(stamp.astimezone().date().isoformat(), row['game_id'])]+=len(japanese_characters(row['line_text'] or ''))
            # Preserve GSM's logged reading time where a daily game rollup exists.
            for group, keys in groups.items():
                if group not in durations:
                    continue
                total = original_characters[group]
                if total:
                    store.db.executemany('UPDATE readings SET seconds=characters*? WHERE key=?',
                        [(durations[group] / total, key) for key in keys])
        finally:
            store.batching = False
    return changed


def manga_volumes(snapshots):
    # Aliases can hold the same synced volume; use its latest state once.
    volumes = {}
    for snapshot in snapshots:
        for identifier, row in snapshot['volumes'].items():
            if not isinstance(row, dict) or identifier == 'series':
                continue
            previous = volumes.get(identifier)
            if previous is None or row.get('lastProgressUpdate', '') > previous.get('lastProgressUpdate', ''):
                volumes[identifier] = row
    return volumes


def manga_records(snapshots,cutoff=0):
    volumes = manga_volumes(snapshots)
    records = []
    for identifier, row in volumes.items():
        chars = int(row.get('chars', 0))
        if row.get('deletedOn') or (chars <= 0 and not row.get('archivedReads')):
            continue
        label = 'Manga · ' + str(row.get('volume_title') or row.get('series_title') or identifier)
        turns = sorted((t for t in row.get('recentPageTurns', []) if len(t) >= 3), key=lambda t:t[0])
        buckets = defaultdict(lambda: [0, 0])
        high = 0
        previous = None
        for stamp_ms, page, cumulative in turns:
            stamp = datetime.fromtimestamp(stamp_ms / 1000, timezone.utc).astimezone()
            day = study_date(stamp,cutoff).isoformat()
            count = min(chars, max(0, int(cumulative)))
            if count > high:
                buckets[day][0] += count - high
                high = count
            if previous is not None and 0 < stamp_ms - previous <= 120000:
                buckets[day][1] += (stamp_ms - previous) / 1000
            previous = stamp_ms
        fallback = study_date(local_timestamp(row.get('completedAt') or row.get('lastProgressUpdate')),cutoff).isoformat()
        if chars > high:
            buckets[fallback][0] += chars - high
        # Preserve the reader's recorded timer if it exceeds surviving page-turn time.
        recorded = float(row.get('timeReadInMinutes', 0)) * 60
        measured = sum(v[1] for v in buckets.values())
        if recorded > measured and chars > 0:
            for values in buckets.values():
                values[1] += (recorded - measured) * values[0] / chars
        for index, archived in enumerate(row.get('archivedReads', [])):
            when = archived.get('completedAt') or datetime.fromtimestamp(archived['at']/1000,timezone.utc).isoformat()
            day = study_date(local_timestamp(when),cutoff).isoformat()
            count = int(archived.get('chars', 0))
            if count > 0:
                records.append((f'manga:{identifier}:archived:{index}', day, label, count, 0, 'import', 0, 0))
        for day, (count, seconds) in buckets.items():
            if count:
                records.append((f'manga:{identifier}:{day}', day, label, count, seconds, 'import', 0, 0))
    return records


def import_manga(store, path):
    snapshots = json.loads(Path(path).read_text())
    volumes = manga_volumes(snapshots)
    versions = store.preference('manga_volume_versions', {})
    current = {}
    for identifier, row in volumes.items():
        stamp = local_timestamp(row.get('lastProgressUpdate') or row.get('completedAt')).timestamp()
        if stamp >= versions.get(identifier, 0):
            current[identifier] = row
            versions[identifier] = stamp
    records = manga_records([{'volumes': current}],store.day_cutoff_hour())
    with store.db:
        for identifier in current:
            prefix = f'manga:{identifier}:'
            store.db.execute('DELETE FROM readings WHERE substr(key,1,?)=?', (len(prefix), prefix))
        store.db.executemany('INSERT OR REPLACE INTO readings SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM reading_deleted WHERE key=?)', [(*row,row[0]) for row in records])
        store.db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)', ('manga_volume_versions', json.dumps(versions)))
    return len(records)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=Path.home()/'.config/yomitan-floating/reading-stats.sqlite3')
    parser.add_argument('--gsm', type=Path)
    parser.add_argument('--manga', type=Path)
    args = parser.parse_args()
    store = ReadingStats(args.database)
    if args.gsm:
        print('GSM records added/updated:', import_gsm(store, args.gsm))
    if args.manga:
        print('Manga daily records:', import_manga(store, args.manga))
    summary = store.summary()
    print('Combined Japanese characters:', summary['total'])
    print('Reading days:', summary['active_days'])
    print('Sources:', len(summary['sources']))
    store.db.close()
