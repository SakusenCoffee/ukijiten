import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mokuro_cloud import config_command, config_path, read_progress, connect_mega
import configparser


class CloudTests(unittest.TestCase):
    def test_provider_commands_have_private_config_and_read_only_scopes(self):
        with tempfile.TemporaryDirectory() as directory,patch('mokuro_cloud.binary',return_value='/usr/bin/rclone'):
            for provider in ('google_drive','mega','onedrive'):
                command=config_command(directory,provider)
                self.assertIn('mokuro_'+provider,command)
                self.assertIn('--non-interactive',command)
                self.assertEqual(os.stat(config_path(directory)).st_mode & 0o777,0o600)
            self.assertIn('drive.readonly',config_command(directory,'google_drive'))
            scopes=config_command(directory,'onedrive')
            self.assertFalse(any('ReadWrite' in s for s in scopes))

    def test_mega_form_credentials_use_stdin_and_preserve_other_accounts(self):
        with tempfile.TemporaryDirectory() as directory,patch('mokuro_cloud.binary',return_value='rclone'):
            path=Path(config_path(directory));path.write_text('[mokuro_google_drive]\ntype = drive\ntoken = keep-token\n')
            calls=[]
            def run(command,**kwargs):
                calls.append((command,kwargs))
                if 'obscure' in command:
                    self.assertNotIn('private-password',command)
                    self.assertEqual(kwargs['input'],'private-password')
                    return subprocess.CompletedProcess(command,0,stdout='obscured-value\n')
                return subprocess.CompletedProcess(command,0)
            with patch('mokuro_cloud.subprocess.run',side_effect=run):connect_mega(directory,'user@example.org','private-password','123456')
            settings=configparser.ConfigParser();settings.read(path)
            self.assertEqual(settings['mokuro_google_drive']['token'],'keep-token')
            self.assertEqual(settings['mokuro_mega']['pass'],'obscured-value')
            self.assertIn('lsf',calls[1][0])
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_cloud_read_normalizes_progress_and_does_not_write_remote(self):
        with tempfile.TemporaryDirectory() as directory,patch('mokuro_cloud.binary',return_value='rclone'):
            def run(command,stdout,**kwargs):
                self.assertIn('cat',command)
                self.assertIn('mokuro_mega:mokuro-reader/volume-data.json',command)
                stdout.write(json.dumps({'book':{'chars':40}}).encode())
                return subprocess.CompletedProcess(command,0)
            with patch('mokuro_cloud.subprocess.run',side_effect=run):
                self.assertEqual(read_progress(directory,'mega','mokuro-reader/volume-data.json')[0]['volumes']['book']['chars'],40)
            with self.assertRaises(ValueError):read_progress(directory,'mega','../secret')

if __name__=='__main__':unittest.main()
