"""Portable source configuration, separate from the reading ledger."""
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def validate_url(value, schemes, label):
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError(f'Invalid {label} address.') from None
    if url.scheme not in schemes or not url.hostname or url.username or url.password:
        raise ValueError(f'Invalid {label} address.')
    return value.rstrip('/')


class StatsSettings:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'stats-sources.json'
        home = Path.home()
        paths = sorted({str(p) for pattern in (
            '.local/share/Anki2/*/collection.anki2', 'Library/Application Support/Anki2/*/collection.anki2',
            '.var/app/net.ankiweb.Anki/data/Anki2/*/collection.anki2',
            '.local/share/anki-sync-server/data/*/collection.anki2') for p in home.glob(pattern)})
        defaults = {
            'day': {'cutoff_hour': 0},
            'gsm': {'enabled': True, 'url': 'ws://127.0.0.1:55000/ws/texthooker'},
            'gsm_history': {'enabled': False, 'path': ''},
            'mokuro_browser': {'enabled': (home/'.local/share/mokuro-browser/reading-history.sqlite3').is_file(), 'path': str(home/'.local/share/mokuro-browser/reading-history.sqlite3')},
            'anki': {'enabled': False, 'backend': 'connect',
                     'url': 'http://127.0.0.1:8765', 'key': '', 'decks': [], 'paths': paths},
            'mokuro': {'enabled': False, 'paths': [],
                'webdav': {'enabled': False, 'webdav_server_url': '', 'webdav_username': '',
                           'webdav_password': '', 'webdav_token': ''},
                'google_drive': {'enabled': False, 'path': 'mokuro-reader/volume-data.json'},
                'mega': {'enabled': False, 'path': 'mokuro-reader/volume-data.json'},
                'onedrive': {'enabled': False, 'path': 'mokuro-reader/volume-data.json'},
                'local_folder': {'enabled': False, 'path': ''}},
            'files': {'enabled': True, 'paths': []},
            'ttsu': {'enabled': False, 'paths': [],'folder':''},
            'jpdb': {'enabled': False, 'paths': [],'include_activity':True,'include_anki_reviews':False},
            'renshuu': {'enabled': False, 'paths': [],'key':'','include_activity':True},
        }
        for name in ('gsm','mokuro','mokuro_browser','files','ttsu'):defaults[name].update(include_time=True,include_characters=True)
        defaults['anki']['include_time']=True
        legacy = self.directory / 'import-sources/mangaseedbox-connection.json'
        if legacy.exists():
            try:
                defaults['mokuro']['webdav'].update(json.loads(legacy.read_text()))
                defaults['mokuro']['webdav']['enabled'] = True
                defaults['mokuro']['enabled'] = True
            except (OSError, ValueError):
                pass
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            saved = {}
        old_webdav = saved.pop('manga', None)
        mokuro = saved.get('mokuro', {})
        if old_webdav:
            mokuro['webdav'] = old_webdav
            mokuro['enabled'] = bool(mokuro.get('enabled') or old_webdav.get('enabled'))
            saved['mokuro'] = mokuro
        self.values = {name: dict(value, **saved.get(name, {})) for name, value in defaults.items()}
        for provider in ('webdav','google_drive','mega','onedrive','local_folder'):
            self.values['mokuro'][provider] = dict(defaults['mokuro'][provider], **mokuro.get(provider, {}))
        if not self.path.exists():
            # Preserve the existing personal deck selection during migration only.
            if (self.directory / 'reading-stats.sqlite3').exists() and paths:
                import sqlite3
                try:
                    from contextlib import closing
                    with closing(sqlite3.connect(self.directory / 'reading-stats.sqlite3')) as db:
                        decks = [row[0] for row in db.execute('SELECT deck FROM anki_deck_totals')]
                    self.values['anki']['decks'] = decks
                    self.values['anki']['enabled'] = bool(decks)
                    if decks:
                        self.values['anki']['backend'] = 'collection'
                except sqlite3.Error:
                    pass
            self.save(self.values)
        elif old_webdav:
            self.save(self.values)

    def public(self):
        values = copy.deepcopy(self.values)
        values['anki']['key_saved'] = bool(values['anki'].pop('key', ''))
        values['renshuu']['key_saved']=bool(values['renshuu'].pop('key',''))
        for field in ('webdav_password', 'webdav_token'):
            values['mokuro']['webdav'][field+'_saved'] = bool(values['mokuro']['webdav'].pop(field, ''))
        return values

    def save(self, incoming):
        values = copy.deepcopy(self.values)
        if not isinstance(incoming, dict):
            raise ValueError('Invalid source settings.')
        for name, fields in values.items():
            supplied = incoming.get(name, {})
            if not isinstance(supplied, dict):
                raise ValueError('Invalid source settings.')
            for field in fields:
                if field in supplied:
                    if isinstance(fields[field], dict):
                        fields[field].update({key:value for key,value in supplied[field].items() if key in fields[field]})
                    else:
                        fields[field] = supplied[field]
            if name=='day':
                from study_day import validate_cutoff
                validate_cutoff(fields['cutoff_hour'])
                continue
            if type(fields['enabled']) is not bool:
                raise ValueError('Invalid source switch.')
            if any(type(value) is not bool for field,value in fields.items() if field.startswith('include_')):raise ValueError('Invalid data selection.')
        for name, schemes in [('gsm', ('ws', 'wss')), ('anki', ('http', 'https'))]:
            values[name]['url'] = validate_url(str(values[name]['url']), schemes, name.upper())
        if values['anki']['backend'] not in ('connect', 'collection'):
            raise ValueError('Choose an Anki connection type.')
        for source in ('anki','renshuu'):
            if not isinstance(values[source]['key'],str):raise ValueError('Invalid API key.')
        if not isinstance(values['ttsu']['folder'],str):raise ValueError('Invalid Ttsu export folder.')
        if not isinstance(values['mokuro_browser']['path'],str) or not values['mokuro_browser']['path'].strip():raise ValueError('Enter the Mokuro Browser history database path.')
        for source, field in [('anki', 'decks'), ('anki', 'paths'), ('mokuro', 'paths'), ('files', 'paths'),('ttsu','paths'),('jpdb','paths'),('renshuu','paths')]:
            items = values[source][field]
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ValueError('Invalid deck or file list.')
            values[source][field] = list(dict.fromkeys(item.strip() for item in items if item.strip()))
        anki = values['anki']
        if anki['enabled'] and not anki['decks']:
            raise ValueError('Select at least one Anki deck.')
        if anki['enabled'] and anki['backend'] == 'collection' and not anki['paths']:
            raise ValueError('Choose an Anki collection file.')
        if values['gsm_history']['enabled'] and not values['gsm_history']['path']:
            raise ValueError('Choose a GSM database.')
        mokuro = values['mokuro']
        for provider in ('webdav','google_drive','mega','onedrive','local_folder'):
            if type(mokuro[provider]['enabled']) is not bool:
                raise ValueError('Invalid Mokuro source switch.')
        webdav = mokuro['webdav']
        if mokuro['enabled'] and webdav['enabled'] and (not webdav['webdav_server_url'] or not (webdav['webdav_password'] or webdav['webdav_token'])):
            raise ValueError('Enter the WebDAV address and login.')
        if webdav['webdav_server_url']:
            webdav['webdav_server_url'] = validate_url(webdav['webdav_server_url'], ('http', 'https'), 'WebDAV')
            url = urlsplit(webdav['webdav_server_url'])
            if url.scheme != 'https' and url.hostname not in ('localhost', '127.0.0.1'):
                raise ValueError('Use HTTPS for WebDAV.')
        if mokuro['enabled'] and mokuro['local_folder']['enabled'] and not mokuro['local_folder']['path']:
            raise ValueError('Choose the local Mokuro folder.')
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with open(temporary, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
            json.dump(values, stream, ensure_ascii=False, indent=2)
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        self.values = values
