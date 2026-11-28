import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anki_change_monitor import AnkiRefresh, local_collection_stamp


class AnkiChangeTests(unittest.TestCase):
    def test_local_profile_and_wal_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            collection = home / '.local/share/Anki2/Profile/collection.anki2'
            collection.parent.mkdir(parents=True); collection.write_bytes(b'db')
            config = {'url':'http://127.0.0.1:8765', 'paths':[]}
            with patch('anki_change_monitor.Path.home', return_value=home), patch('anki_change_monitor.anki_request', return_value='Profile'):
                first = local_collection_stamp(config)
                self.assertIsNotNone(first)
                wal = Path(str(collection) + '-wal'); wal.write_bytes(b'new review')
                self.assertNotEqual(first, local_collection_stamp(config))
                wal.unlink(); collection.unlink()
                self.assertIsNone(local_collection_stamp(config))
                self.assertIsNone(local_collection_stamp({**config, 'url':'https://remote.example'}))

    def test_only_successful_snapshots_reused_and_config_invalidates(self):
        cache = AnkiRefresh(); config = {'backend':'connect', 'decks':['A']}
        with patch('anki_change_monitor.local_collection_stamp', return_value=('profile', 'one')) as stamp, patch('anki_change_monitor.refresh_anki', return_value={'reviews':3}) as refresh:
            self.assertEqual(cache.run(None, config), {'reviews':3})
            cache.run(None, config); self.assertEqual(refresh.call_count, 1)
            cache.run(None, {**config, 'decks':['B']}); self.assertEqual(refresh.call_count, 2)
            stamp.return_value = ('profile','two')
            refresh.side_effect = ValueError('temporarily unavailable')
            with self.assertRaises(ValueError): cache.run(None, config)
            refresh.side_effect = None
            cache.run(None, config); self.assertEqual(refresh.call_count, 4)
            stamp.return_value = None
            cache.run(None, config); cache.run(None, config)
            self.assertEqual(refresh.call_count, 6)
