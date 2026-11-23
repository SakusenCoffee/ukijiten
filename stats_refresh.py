"""Explicit refresh of Anki review time and authenticated Mokuro WebDAV progress."""
import base64
import json
import os
import sqlite3
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from anki_stats import import_review_time
from history_import import import_manga
from reading_stats import ReadingStats


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(request.full_url), urllib.parse.urlsplit(newurl)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            raise ValueError('Mokuro WebDAV redirected to a different server; login was not forwarded.')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_webdav(connection_path):
    try:
        connection = connection_path if isinstance(connection_path, dict) else json.loads(Path(connection_path).read_text())
    except FileNotFoundError:
        raise ValueError('Mokuro WebDAV connection needs a saved login.') from None
    root = connection['webdav_server_url'].rstrip('/')
    parsed = urllib.parse.urlsplit(root)
    if parsed.username or parsed.password or not parsed.hostname:
        raise ValueError('Invalid Mokuro WebDAV connection address.')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
        raise ValueError('Mokuro WebDAV requires HTTPS.')
    username = connection.get('webdav_username', '')
    password = connection.get('webdav_password', '')
    token = connection.get('webdav_token', '')
    if password:
        authorization = 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()
    elif token:
        authorization = 'Bearer ' + token
    else:
        raise ValueError('Mokuro WebDAV connection needs a saved login.')
    request = urllib.request.Request(root + '/mokuro-reader/volume-data.json', headers={
        'Authorization': authorization, 'Accept': 'application/json', 'Cache-Control': 'no-cache'})
    try:
        with urllib.request.build_opener(SameOriginRedirect()).open(request, timeout=20) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code in (401, 403):
            raise ValueError('Mokuro WebDAV login needs updating.') from None
        raise ValueError(f'Mokuro WebDAV returned HTTP {error.code}.') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('Mokuro WebDAV is unavailable; saved stats were kept.') from None
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('Mokuro WebDAV history exceeds the download limit.')
    try:
        volumes = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('Mokuro WebDAV returned invalid reading history.') from None
    if not isinstance(volumes, dict) or not all(isinstance(row, dict) for row in volumes.values()):
        raise ValueError('Mokuro WebDAV returned invalid reading history.')
    return {'origin': root, 'volumes': volumes}


def refresh_sources(database, anki_paths, connection_path):
    results = []
    store = ReadingStats(database)
    try:
        try:
            result = import_review_time(store, anki_paths)
            results.append(f"Anki updated ({result['reviews']:,} reviews)")
        except (ValueError, OSError, sqlite3.Error):
            results.append('Anki unavailable; saved time was kept')
        try:
            remote = fetch_webdav(connection_path)
            source_dir = Path(connection_path).parent
            snapshots = [remote]
            local = source_dir / 'manga-browser-progress.json'
            if local.exists():
                snapshots += json.loads(local.read_text())
            path = source_dir / 'mokuro-webdav-refresh.json'
            # This file contains progress only; login stays in its separate private file.
            with open(path, 'w', opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                json.dump(snapshots, output)
            imported = import_manga(store, path)
            results.append(f'Mokuro WebDAV updated ({imported} daily records)')
        except (ValueError, OSError, KeyError, TypeError) as error:
            results.append(str(error) if isinstance(error, ValueError) else 'Mokuro WebDAV unavailable; saved stats were kept')
    finally:
        store.db.close()
    return ' · '.join(results)


def refresh_configured(database, settings, source_dir):
    from anki_stats import refresh_anki
    from import_assets import import_path, import_snapshot
    from mokuro_cloud import read_progress
    store = ReadingStats(database)
    results = []
    def run(name, operation):
        try:
            result = operation()
            results.append(f'{name} updated' + (f" ({result['characters']:+,} characters)" if isinstance(result,dict) and 'characters' in result else f' ({result} records)' if isinstance(result, int) else ''))
        except Exception as error:
            results.append(f'{name}: {error}' if isinstance(error, ValueError) else f'{name} unavailable; saved stats kept')
    def cloud_snapshot(data,identifier,name):
        before=store.summary()['total']
        import_snapshot(store,data,identifier,name,restore_deleted=True)
        return {'characters':store.summary()['total']-before}
    try:
        browser=settings.get('mokuro_browser',{})
        if browser.get('enabled'):
            from mokuro_browser_stats import sync_history
            run('Mokuro Browser',lambda:sync_history(store,browser['path']))
        if settings['anki']['enabled']:
            run('Anki', lambda: refresh_anki(store, settings['anki']))
        if settings['gsm_history']['enabled']:
            run('GSM history', lambda: import_path(store, settings['gsm_history']['path'], 'gsm_history'))
        mokuro = settings['mokuro']
        if mokuro['enabled']:
            if mokuro['webdav']['enabled']:
                run('Mokuro WebDAV', lambda: cloud_snapshot([fetch_webdav(mokuro['webdav'])], 'cloud:webdav', 'WebDAV history'))
            for provider, label in [('google_drive','Google Drive'),('mega','MEGA'),('onedrive','OneDrive')]:
                if mokuro[provider]['enabled']:
                    run('Mokuro '+label, lambda provider=provider,label=label: cloud_snapshot(
                        read_progress(Path(source_dir).parent, provider, mokuro[provider]['path']), 'cloud:'+provider,label+' history'))
            if mokuro['local_folder']['enabled']:
                def local():
                    folder=Path(mokuro['local_folder']['path']).expanduser()
                    path=folder/'volume-data.json'
                    if not path.is_file():path=folder/'mokuro-reader/volume-data.json'
                    return import_path(store,path,'mokuro')
                run('Mokuro local folder',local)
            for path in mokuro['paths']:
                run('Mokuro', lambda path=path: import_path(store,path,'mokuro'))
        if settings['files']['enabled']:
            for path in settings['files']['paths']:
                run(Path(path).name, lambda path=path: import_path(store,path,'files'))
        ttsu=settings.get('ttsu',{})
        if ttsu.get('enabled'):
            paths=list(ttsu.get('paths',[]))
            if ttsu.get('folder'):paths+=list(Path(ttsu['folder']).expanduser().rglob('statistics_*.json'))[:1000]
            for path in dict.fromkeys(map(str,paths)):run('Ttsu',lambda path=path:import_path(store,path,'ttsu'))
        for service in ('jpdb','renshuu'):
            conf=settings.get(service,{})
            if conf.get('enabled'):
                for path in conf.get('paths',[]):run(service,lambda path=path,service=service:import_path(store,path,service))
                if service=='renshuu' and conf.get('key'):
                    from study_imports import fetch_renshuu,ingest_study
                    run('Renshuu',lambda:ingest_study(store,'renshuu:api','Renshuu API','','renshuu',fetch_renshuu(conf['key'])))
    finally:
        store.db.close()
    return ' · '.join(results) or 'No refresh sources enabled.'


def import_mokuro(store, filename):
    path = Path(filename).expanduser()
    raw = json.loads(path.read_text())
    if isinstance(raw, list):
        snapshots = raw
    elif isinstance(raw, dict):
        snapshots = [raw] if 'volumes' in raw else [{'volumes': raw}]
    else:
        raise ValueError('Choose a Mokuro volume-data.json export.')
    # Normalize the export without modifying its source file.
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        copy = Path(directory) / 'progress.json'
        copy.write_text(json.dumps(snapshots))
        return import_manga(store, copy)
