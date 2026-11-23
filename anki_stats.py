"""Read review time from Anki collection snapshots without opening them in Anki."""
from datetime import datetime
from pathlib import Path
import sqlite3
import hashlib
import json


def config_version(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()

TARGET_DECKS = ('Kaishi 1.5k', 'Mining')


def collection_reviews(path, targets=TARGET_DECKS):
    path = Path(path)
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        connection.execute('BEGIN')
        names = {}
        normalized = {name.replace(' ', '').casefold(): name for name in targets}
        for deck_id, name in connection.execute('SELECT id,name FROM decks'):
            full = name.replace('\x1f', '::').replace(' ', '').casefold()
            target = next((normalized[t] for t in sorted(normalized, key=len, reverse=True) if full == t or full.startswith(t + '::')), None)
            if target:
                names[deck_id] = target
        if not names:
            return []
        marks = ','.join('?' for _ in names)
        rows = connection.execute(f'''SELECT r.id,r.time,CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END
            FROM revlog r JOIN cards c ON c.id=r.cid
            WHERE CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END IN ({marks})''', list(names)).fetchall()
        return [(int(identifier), datetime.fromtimestamp(identifier/1000).astimezone().date().isoformat(),
                 names[deck], max(0, int(milliseconds))) for identifier, milliseconds, deck in rows]
    finally:
        connection.close()


def import_review_time(store, paths, targets=TARGET_DECKS):
    candidates = []
    errors = []
    for path in paths:
        if not Path(path).is_file():
            continue
        try:
            rows = collection_reviews(path, targets)
            if rows:
                candidates.append((max(row[0] for row in rows), rows, str(path)))
        except (sqlite3.Error, ValueError, OverflowError) as error:
            errors.append(str(error))
    if not candidates:
        raise ValueError('No review history available for the selected Anki decks.' + (' '+errors[0] if errors else ''))
    # Union review IDs so unsynced desktop reviews survive newer mobile/server reviews.
    # Where copies disagree, prefer the collection with the newest selected review.
    merged = {}
    for _, candidate_rows, _ in sorted(candidates, key=lambda candidate:candidate[0]):
        merged.update((row[0], row) for row in candidate_rows)
    rows = list(merged.values())
    source = ';'.join(candidate[2] for candidate in candidates)
    replace_reviews(store, rows)
    return {'source':source,'reviews':len(rows),'seconds':sum(row[3] for row in rows)/1000}


def replace_reviews(store, rows):
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        expected = getattr(store, 'anki_configuration', None)
        if expected and store.preference('anki_config_version', expected) != expected:
            raise ValueError('Anki settings changed. Reload to update the selected decks.')
        store.db.execute('CREATE TABLE IF NOT EXISTS anki_reviews (id INTEGER PRIMARY KEY,day TEXT NOT NULL,deck TEXT NOT NULL,milliseconds INTEGER NOT NULL)')
        store.db.executemany('INSERT INTO anki_reviews VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET day=excluded.day,deck=excluded.deck,milliseconds=excluded.milliseconds WHERE day!=excluded.day OR deck!=excluded.deck OR milliseconds!=excluded.milliseconds', rows)
        # Reconcile deleted/moved cards while keeping all time from the authoritative snapshot.
        store.db.execute('CREATE TEMP TABLE IF NOT EXISTS current_anki_reviews(id INTEGER PRIMARY KEY)')
        store.db.execute('DELETE FROM current_anki_reviews')
        store.db.executemany('INSERT INTO current_anki_reviews VALUES (?)', [(row[0],) for row in rows])
        store.db.execute('DELETE FROM anki_reviews WHERE id NOT IN (SELECT id FROM current_anki_reviews)')
        store.db.execute('DELETE FROM anki_daily')
        store.db.execute('INSERT INTO anki_daily SELECT day,SUM(milliseconds),COUNT(*) FROM anki_reviews GROUP BY day')
        store.db.execute('DELETE FROM anki_deck_totals')
        store.db.execute('INSERT INTO anki_deck_totals SELECT deck,SUM(milliseconds),COUNT(*) FROM anki_reviews GROUP BY deck')


def anki_request(config, action, **params):
    import json
    import urllib.request
    from stats_settings import validate_url
    url = validate_url(config['url'], ('http', 'https'), 'AnkiConnect')
    payload = {'action': action, 'version': 6, 'params': params}
    if config.get('key'):
        payload['key'] = config['key']
    request = urllib.request.Request(url, json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
    except (OSError, ValueError):
        raise ValueError('AnkiConnect unavailable. Open Anki and check its address and API key.') from None
    if not isinstance(data, dict) or data.get('error'):
        raise ValueError('AnkiConnect: ' + str(data.get('error', 'invalid response')) if isinstance(data, dict) else 'Invalid AnkiConnect response.')
    return data.get('result')


def available_decks(config):
    if config['backend'] == 'connect':
        return sorted(anki_request(config, 'deckNames'))
    names = set()
    for source in config['paths']:
        with sqlite3.connect(Path(source).expanduser().resolve().as_uri() + '?mode=ro', uri=True) as db:
            names.update(name.replace('\x1f', '::') for (name,) in db.execute('SELECT name FROM decks'))
    return sorted(names)


def import_connect_reviews(store, config):
    targets = config['decks']
    if not targets:
        raise ValueError('Select at least one Anki deck in Stats settings.')
    rows = {}
    # Longest matching deck wins when both a parent and its subdeck are selected.
    assigned = set()
    for deck in sorted(targets, key=len, reverse=True):
        escaped = deck.replace('\\', '\\\\').replace('"', '\\"')
        cards = anki_request(config, 'findCards', query='deck:"' + escaped + '"')
        if not isinstance(cards, list):
            raise ValueError('Invalid AnkiConnect card list.')
        cards = [card for card in cards if card not in assigned]
        assigned.update(cards)
        for offset in range(0, len(cards), 500):
            reviews = anki_request(config, 'getReviewsOfCards', cards=cards[offset:offset+500])
            if not isinstance(reviews, dict):
                raise ValueError('Invalid AnkiConnect review history.')
            for history in reviews.values():
                for review in history:
                    identifier, milliseconds = int(review['id']), max(0, int(review['time']))
                    day = datetime.fromtimestamp(identifier / 1000).astimezone().date().isoformat()
                    rows[identifier] = (identifier, day, deck, milliseconds)
    replace_reviews(store, list(rows.values()))
    return {'source': 'AnkiConnect', 'reviews': len(rows), 'seconds': sum(row[3] for row in rows.values()) / 1000}


def refresh_anki(store, config):
    store.anki_configuration = config_version(config)
    if not config['decks']:
        raise ValueError('Select at least one Anki deck in Stats settings.')
    if config['backend'] == 'connect':
        return import_connect_reviews(store, config)
    paths = [Path(path).expanduser() for path in config['paths']]
    # An empty, readable selected history is a valid replacement too.
    if paths and any(path.is_file() for path in paths):
        all_rows = [collection_reviews(path, config['decks']) for path in paths if path.is_file()]
        if all(not rows for rows in all_rows):
            replace_reviews(store, [])
            return {'source': 'collections', 'reviews': 0, 'seconds': 0}
    return import_review_time(store, paths, config['decks'])
