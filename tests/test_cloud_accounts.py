import configparser
from concurrent.futures import Future
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mokuro_cloud import (connection_summary,connection_update,disconnect_account,identify_account,read_progress,CloudAuthRequired,reset_interrupted_connections)
from browser_cloud import BrowserCloudConnection
from floating_dictionary import FloatingDictionary


def credentials(directory):
    path=Path(directory)/'mokuro-cloud.conf'
    path.write_text('[mokuro_google_drive]\ntype=drive\ntoken={"access_token":"private-token","refresh_token":"private-refresh"}\n[mokuro_mega]\ntype=mega\nuser=user@example.org\npass=obscured-password\n')
    path.chmod(0o600)
    return path


class AccountTests(unittest.TestCase):
    def test_settings_use_cached_identity_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            credentials(directory)
            connection_update(directory,'google_drive',state='connected',account='user@example.org')
            with patch('mokuro_cloud.subprocess.run',side_effect=AssertionError('Settings contacted cloud')):
                status=connection_summary(directory)
            self.assertEqual(status['google_drive']['account'],'user@example.org')
            self.assertEqual(status['google_drive']['state'],'connected')
            self.assertNotIn('private-token',json.dumps(status))
            self.assertEqual((Path(directory)/'cloud-accounts.json').stat().st_mode & 0o777,0o600)

    def test_interrupted_login_is_reset_without_network_on_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            connection_update(directory,'google_drive',state='connecting')
            with patch('mokuro_cloud.subprocess.run',side_effect=AssertionError('Startup contacted cloud')):
                reset_interrupted_connections(directory)
            self.assertEqual(connection_summary(directory)['google_drive']['state'],'disconnected')

    def test_disconnect_removes_only_chosen_account_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path=credentials(directory)
            connection_update(directory,'google_drive',state='connected',account='user@example.org')
            disconnect_account(directory,'google_drive')
            parser=configparser.ConfigParser();parser.read(path)
            self.assertFalse(parser.has_section('mokuro_google_drive'))
            self.assertEqual(parser['mokuro_mega']['user'],'user@example.org')
            self.assertEqual(connection_summary(directory)['google_drive']['account'],'')
            self.assertEqual(connection_summary(directory)['google_drive']['state'],'disconnected')

    def test_expired_auth_marks_status_but_never_opens_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            credentials(directory)
            def run(command,stdout,stderr,**kwargs):
                stderr.write(b'Failed to refresh token: invalid_grant')
                return MagicMock(returncode=1)
            with patch('mokuro_cloud.binary',return_value='rclone'),patch('mokuro_cloud.subprocess.run',side_effect=run),patch('webbrowser.open') as browser:
                with self.assertRaises(CloudAuthRequired):read_progress(directory,'google_drive','mokuro-reader/volume-data.json')
                browser.assert_not_called()
            self.assertEqual(connection_summary(directory)['google_drive']['state'],'needs_auth')

    def test_userinfo_extracts_account_without_exposing_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            credentials(directory)
            response=MagicMock();response.read.return_value=json.dumps({'user':{'emailAddress':'account@example.org','displayName':'Name'}}).encode()
            opener=MagicMock();opener.open.return_value.__enter__.return_value=response
            with patch('mokuro_cloud.urllib.request.build_opener',return_value=opener):
                self.assertEqual(identify_account(directory,'google_drive'),'account@example.org')

    def test_browser_connection_has_no_native_dialog_or_setup_window(self):
        with tempfile.TemporaryDirectory() as directory:
            credentials(directory);connection=BrowserCloudConnection(directory,'google_drive')
            try:
                responses=[json.dumps({'State':'step','Option':{'Name':'config_is_local','Default':False}}),json.dumps({'State':''})]
                with patch('browser_cloud.binary',return_value='rclone'),patch('browser_cloud.config_command',return_value=['rclone']),patch.object(connection,'command',side_effect=responses),patch('browser_cloud.identify_account',return_value='user@example.org'),patch.object(connection,'request',side_effect=AssertionError('Unnecessary setup browser page')):
                    self.assertTrue(connection.run())
                self.assertEqual(connection_summary(directory)['google_drive']['account'],'user@example.org')
            finally:connection.close()

    def test_browser_credentials_are_not_in_page_state_and_cross_origin_posts_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            connection=BrowserCloudConnection(directory,'mega')
            try:
                connection.start_server();connection.page_state={'generation':'test','title':'MEGA','fields':[]}
                request=urllib.request.Request(connection.address+'answer',json.dumps({'generation':'test','password':'secret'}).encode(),{'Content-Type':'application/json','Origin':'https://untrusted.example'})
                with self.assertRaises(urllib.error.HTTPError) as rejected:urllib.request.urlopen(request)
                rejected.exception.close()
                self.assertIsNone(connection.answer)
                request=urllib.request.Request(connection.address+'answer',json.dumps({'generation':'test','password':'secret'}).encode(),{'Content-Type':'application/json','Origin':connection.origin})
                with urllib.request.urlopen(request) as response:self.assertEqual(response.status,204)
                self.assertNotIn('secret',json.dumps(connection.page_state))
            finally:connection.close()

    def test_refresh_prompts_once_then_does_not_loop_for_failed_new_credentials(self):
        owner=MagicMock()
        done=Future();done.set_result('Sign-in required')
        owner.stats_refresh_future=done
        owner.refresh_auth_attempted=set()
        owner.source_settings.values={'mokuro':{'enabled':True,'google_drive':{'enabled':True},'mega':{'enabled':False},'onedrive':{'enabled':False}}}
        states={key:{'state':'needs_auth'} for key in ('google_drive','mega','onedrive')}
        with patch('floating_dictionary.connection_summary',return_value=states):
            FloatingDictionary.finish_stats_refresh(owner)
            self.assertEqual(owner.refresh_auth_queue,['google_drive'])
            self.assertEqual(owner.refresh_auth_attempted,{'google_drive'})
            owner.stats_refresh_future=done
            FloatingDictionary.finish_stats_refresh(owner)
            self.assertEqual(owner.refresh_auth_queue,[])

if __name__=='__main__':unittest.main()
