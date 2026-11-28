"""Avoid re-reading unchanged local collections through AnkiConnect."""
from pathlib import Path
from urllib.parse import urlsplit

from anki_stats import anki_request, config_version, refresh_anki


def local_collection_stamp(config):
    """Return a conservative file signature, or None for unverified sources.

    The API still supplies the review data. Local files only tell us whether
    another full fetch is necessary. Include the WAL so unsynced reviews count.
    """
    url = urlsplit(config.get('url', ''))
    if url.hostname not in ('localhost', '127.0.0.1', '::1') or url.path not in ('', '/'):
        return None
    profile = anki_request(config, 'getActiveProfile')
    if not isinstance(profile, str) or not profile or Path(profile).name != profile:
        return None
    home = Path.home()
    roots = (home / '.local/share/Anki2',
             home / '.var/app/net.ankiweb.Anki/data/Anki2')
    paths = {root / profile / 'collection.anki2' for root in roots}
    paths.update(Path(path).expanduser() for path in config.get('paths', ())
                 if Path(path).parent.name == profile)
    stamps = []
    for path in sorted(paths):
        if not path.is_file():
            continue
        for suffix in ('', '-wal', '-journal'):
            source = Path(str(path) + suffix)
            try:
                stat = source.stat()
                stamps.append((str(source), stat.st_dev, stat.st_ino,
                               stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
            except FileNotFoundError:
                stamps.append((str(source), None))
    return (profile, tuple(stamps)) if stamps else None


class AnkiRefresh:
    """Single-worker cache; only successful, stable snapshots are reused."""
    def __init__(self):
        self.stamp = None
        self.result = None

    def run(self, store, config):
        stamp = None
        if config['backend'] == 'connect':
            try:
                local = local_collection_stamp(config)
                if local is not None:
                    stamp = (config_version(config), local)
            except (OSError, ValueError):
                pass  # Remote, unsupported or unavailable: use the normal refresh.
        if stamp is not None and stamp == self.stamp:
            return self.result
        result = refresh_anki(store, config)
        # Keep the pre-fetch stamp: a write during the fetch forces another refresh.
        self.stamp, self.result = stamp, result
        return result
