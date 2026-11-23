"""Read Mokuro progress through provider-specific, privately configured rclone remotes."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

PROVIDERS={'google_drive':('Google Drive','drive'),'mega':('MEGA','mega'),'onedrive':('OneDrive','onedrive')}


def binary(directory, install=False):
    installed=shutil.which('rclone')
    if installed:return installed
    target=Path(directory)/'tools'/('rclone.exe' if sys.platform=='win32' else 'rclone')
    if target.is_file():return str(target)
    if not install:raise ValueError('Connect a cloud account first.')
    system={'linux':'linux','darwin':'osx','win32':'windows'}.get(sys.platform)
    arch={'x86_64':'amd64','AMD64':'amd64','aarch64':'arm64','arm64':'arm64'}.get(platform.machine())
    if not system or not arch:raise ValueError('Install rclone for this platform to connect cloud storage.')
    root='https://downloads.rclone.org/'
    with urllib.request.urlopen(urllib.request.Request(root+'version.txt',headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as response:version=response.read().decode().strip().split()[-1]
    if not version.startswith('v') or not all(c.isdigit() or c in 'v.' for c in version):raise ValueError('Invalid cloud helper version.')
    root+=version+'/'
    name=f'rclone-{version}-{system}-{arch}.zip'
    with urllib.request.urlopen(urllib.request.Request(root+'SHA256SUMS',headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as response:checks=response.read().decode()
    expected=next((line.split()[0] for line in checks.splitlines() if len(line.split())==2 and line.split()[-1].lstrip('*')==name),None)
    if not expected:raise ValueError('Cloud helper download could not be verified.')
    with urllib.request.urlopen(urllib.request.Request(root+name,headers={'User-Agent':'Mozilla/5.0'}),timeout=60) as response:data=response.read()
    if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Cloud helper checksum mismatch.')
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member=next(item for item in archive.namelist() if item.endswith('/'+target.name))
        temporary=target.with_suffix('.tmp');temporary.write_bytes(archive.read(member));temporary.chmod(0o700);temporary.replace(target)
    return str(target)


def config_path(directory):
    path=Path(directory)/'mokuro-cloud.conf'
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():path.touch(mode=0o600)
    path.chmod(0o600)
    return str(path)


def config_command(directory, provider, state=None, answer=None):
    if provider not in PROVIDERS:raise ValueError('Unknown cloud provider.')
    command=[binary(directory),'--config',config_path(directory),'config','create' if state is None else 'update',
             'mokuro_'+provider]
    if state is None:
        command += [PROVIDERS[provider][1]]
        if provider=='google_drive':command += ['scope','drive.readonly']
        if provider=='onedrive':command += ['access_scopes','Files.Read Files.Read.All Sites.Read.All User.Read offline_access']
    else:
        command += ['--continue','--state',state,'--result',str(answer)]
    return command+['--non-interactive','--all']


def read_progress(directory, provider, remote_path):
    if provider not in PROVIDERS:raise ValueError('Unknown cloud provider.')
    if not remote_path or remote_path.startswith(('/', '-')) or '..' in remote_path.split('/'):
        raise ValueError('Enter the path to volume-data.json within your cloud drive.')
    import tempfile
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            result=subprocess.run([binary(directory),'--config',config_path(directory),'cat',
                'mokuro_'+provider+':'+remote_path,'--retries','1','--low-level-retries','1','--timeout','20s'],
                stdout=output,stderr=errors,timeout=60)
        except subprocess.TimeoutExpired:
            raise ValueError('The cloud request timed out. Saved history was kept.') from None
        output.seek(0);raw=output.read(32*1024*1024+1);code=result.returncode
        errors.seek(0);error=errors.read(8192).decode(errors='replace')
        if len(raw)>32*1024*1024:raise ValueError('Mokuro history exceeds the download limit.')
    if code:
        if authentication_error(error):
            connection_update(directory,provider,state='needs_auth')
            raise CloudAuthRequired(PROVIDERS[provider][0]+' needs sign-in.')
        connection_update(directory,provider,state='error')
        raise ValueError(f'{PROVIDERS[provider][0]} could not read history. Check the connection and file path.')
    try:
        volumes=json.loads(raw)
        if not isinstance(volumes,dict):raise ValueError()
    except ValueError:raise ValueError('The cloud file is not Mokuro reading history.') from None
    saved=connection_summary(directory)[provider]
    account=saved.get('account','')
    if not account and saved.get('configured'):
        try:account=identify_account(directory,provider)
        except (OSError,ValueError,subprocess.SubprocessError):pass
    connection_update(directory,provider,state='connected',account=account)
    return [{'origin':provider,'volumes':volumes}]


def connect_mega(directory,email,password,code='',is_cancelled=lambda:False):
    import configparser
    command=binary(directory)
    # Obscure through stdin so credentials never become command-line arguments.
    obscured=subprocess.run([command,'obscure','-'],input=password,text=True,capture_output=True,check=True,timeout=10).stdout.strip()
    path=config_path(directory)
    previous=Path(path).read_bytes()
    parser=configparser.ConfigParser(interpolation=None);parser.read(path)
    parser['mokuro_mega']={'type':'mega','user':email,'pass':obscured,'2fa':code,'use_https':'true'}
    temporary=Path(path).with_suffix('.tmp')
    with open(temporary,'w',opener=lambda p,flags:os.open(p,flags,0o600)) as output:parser.write(output)
    with _METADATA_LOCK:
        if is_cancelled():
            temporary.unlink(missing_ok=True)
            return
        temporary.replace(path)
    # Validate the login without changing the remote or requiring a history file.
    try:
        result=subprocess.run([command,'--config',path,'lsf','mokuro_mega:','--max-depth','1','--retries','1'],capture_output=True,timeout=60)
        if result.returncode:raise ValueError('MEGA sign-in failed.')
    except Exception:
        with _METADATA_LOCK:
            if not is_cancelled():Path(path).write_bytes(previous)
        raise


# Connection metadata is cached locally; displaying settings never contacts a cloud.
import configparser
import threading
from datetime import datetime, timezone
_METADATA_LOCK=threading.RLock()


class CloudAuthRequired(ValueError):
    pass


def _read_metadata(directory):
    try:return json.loads((Path(directory)/'cloud-accounts.json').read_text())
    except (OSError,ValueError):return {}


def connection_update(directory,provider,if_active=None,**fields):
    if provider not in PROVIDERS:raise ValueError('Unknown cloud provider.')
    with _METADATA_LOCK:
        if if_active is not None and not if_active():return
        data=_read_metadata(directory)
        data[provider]=dict(data.get(provider,{}),**fields)
        data[provider]['checked_at']=datetime.now(timezone.utc).isoformat()
        path=Path(directory)/'cloud-accounts.json';path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp')
        with open(temp,'w',opener=lambda p,flags:os.open(p,flags,0o600)) as output:json.dump(data,output)
        temp.replace(path)


def connection_summary(directory):
    parser=configparser.ConfigParser(interpolation=None)
    parser.read(Path(directory)/'mokuro-cloud.conf')
    saved=_read_metadata(directory);result={}
    for provider in PROVIDERS:
        section='mokuro_'+provider
        config=dict(parser[section]) if parser.has_section(section) else {}
        if provider=='mega':configured=bool(config.get('user') and config.get('pass'))
        else:
            try:
                token=json.loads(config.get('token','{}'))
                configured=bool(token.get('access_token') or token.get('refresh_token'))
            except ValueError:configured=False
        item=dict(saved.get(provider,{}))
        if not configured and item.get('state') not in ('connecting','needs_auth'):item={'state':'disconnected','account':''}
        else:
            item.setdefault('state','saved');item.setdefault('account',config.get('user','') if provider=='mega' else '')
        item['configured']=configured
        result[provider]=item
    return result


def identify_account(directory,provider):
    parser=configparser.ConfigParser(interpolation=None)
    parser.read(Path(directory)/'mokuro-cloud.conf')
    section='mokuro_'+provider
    if not parser.has_section(section):return ''
    if provider=='mega':return parser.get(section,'user',fallback='')
    try:token=json.loads(parser.get(section,'token',fallback='{}')).get('access_token','')
    except ValueError:token=''
    if not token:return ''
    if provider=='google_drive':
        url='https://www.googleapis.com/drive/v3/about?fields=user'
    else:
        region=parser.get(section,'region',fallback='global')
        host={'global':'graph.microsoft.com','us':'graph.microsoft.us','de':'graph.microsoft.de','cn':'microsoftgraph.chinacloudapi.cn'}.get(region,'graph.microsoft.com')
        url='https://'+host+'/v1.0/me?$select=displayName,mail,userPrincipalName'
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*_):return None
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=15) as response:
        info=json.loads(response.read(262144))
    if provider=='google_drive':info=info.get('user',{})
    info={str(key).lower().replace('_',''):value for key,value in info.items()} if isinstance(info,dict) else {}
    return next((str(info[key]) for key in ('email','emailaddress','mail','userprincipalname','username','login','displayname','name','id') if info.get(key)), '')


def disconnect_account(directory,provider):
    if provider not in PROVIDERS:raise ValueError('Unknown cloud provider.')
    with _METADATA_LOCK:
        path=Path(directory)/'mokuro-cloud.conf'
        parser=configparser.ConfigParser(interpolation=None);parser.read(path)
        parser.remove_section('mokuro_'+provider)
        temp=path.with_suffix('.tmp');path.parent.mkdir(parents=True,exist_ok=True)
        with open(temp,'w',opener=lambda p,flags:os.open(p,flags,0o600)) as output:parser.write(output)
        temp.replace(path)
        connection_update(directory,provider,state='disconnected',account='')


def authentication_error(message):
    text=message.lower()
    return any(word in text for word in ('invalid_grant','invalid_token','token expired','token has expired','token is expired',
        'failed to refresh token','couldn\'t fetch token','could not fetch token','401 unauthorized','status code 401',
        'authentication failed','invalid credentials','couldn\'t login','could not login','didn\'t find section','no such host section'))


def reset_interrupted_connections(directory):
    for provider,info in connection_summary(directory).items():
        if info['state']=='connecting':
            connection_update(directory,provider,state='saved' if info['configured'] else 'disconnected',account='')
