import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import stat
import sys
import tempfile
from threading import Event,Thread
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import translation


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.settings=translation.TranslationSettings(self.directory.name)

    def test_private_settings_preserve_keys_and_profiles(self):
        self.settings.save({'layout':'rows'})
        self.assertEqual(translation.TranslationSettings(self.directory.name).public()['layout'],'rows')
        with self.assertRaises(ValueError):self.settings.save({'layout':'automatic'})
        self.settings.save({'provider':'compatible','profiles':{'compatible':{'url':'https://example.org/v1/','model':'custom','api_key':'secret'}}})
        public=self.settings.public()
        self.assertNotIn('secret',json.dumps(public));self.assertTrue(public['profiles']['compatible']['key_saved'])
        self.settings.save(public)
        self.assertEqual(self.settings.profile()[1]['api_key'],'secret')
        self.assertEqual(stat.S_IMODE(self.settings.path.stat().st_mode),0o600)
        self.settings.save({'profiles':{'compatible':{'api_key':''}}})
        self.assertFalse(self.settings.public()['profiles']['compatible']['key_saved'])
        for url in ('file:///etc/passwd','https://key:secret@example.org','https://example.org?key=secret'):
            with self.assertRaises(ValueError):self.settings.save({'profiles':{'compatible':{'url':url}}})
        with self.assertRaises(ValueError):self.settings.save({'profiles':[]})
        self.settings.path.write_text('[]')
        self.assertEqual(translation.TranslationSettings(self.directory.name).public()['provider'],'ollama')

    def test_offline_detection(self):
        for text,code in [('これは翻訳のテストです。','ja'),('你好，今天很高兴见到你。','zh-CN'),
            ('This is a sample of English text.','en'),('Bonjour, je voudrais traduire cette phrase.','fr'),('안녕하세요. 오늘 날씨가 좋습니다.','ko')]:
            self.assertEqual(translation.detect_language(text)['code'],code)
        self.assertEqual(translation.detect_language(''),{'code':'','name':''})

    def test_provider_requests_and_model_lists(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path,{k.lower():v for k,v in self.headers.items()},None))
                data={'models':[{'name':'test-model'}]} if self.path.endswith('/api/tags') or self.path.startswith('/gemini') else {'data':[{'id':'test-model'}]}
                self.reply(data)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path,{k.lower():v for k,v in self.headers.items()},body))
                content=json.dumps({'source_language':'Japanese','translation':'Good morning.'})
                if self.path.endswith('/api/chat'):data={'message':{'content':content}}
                elif self.path.startswith('/gemini'):data={'candidates':[{'content':{'parts':[{'text':content}]}}]}
                elif self.path.startswith('/anthropic'):data={'content':[{'type':'text','text':content}]}
                else:data={'choices':[{'message':{'content':content}}]}
                self.reply(data)
            def reply(self,data):
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for provider in ('ollama','lmstudio','openai','gemini','anthropic','openrouter','groq','compatible'):
                url=f'http://127.0.0.1:{server.server_port}/{provider}'
                self.settings.save({'provider':provider,'profiles':{provider:{'url':url,'model':'test-model','api_key':'secret'}}})
                result=translation.translate(self.settings,'おはようございます。','en',Event())
                self.assertEqual(result,{'translation':'Good morning.','source_language':'Japanese'})
                _,profile=self.settings.profile();self.assertEqual(translation.load_models(provider,profile),['test-model'])
            gemini=next(row for row in requests if ':generateContent' in row[0]);self.assertEqual(gemini[1]['x-goog-api-key'],'secret')
            claude=next(row for row in requests if row[0].endswith('/messages'));self.assertEqual(claude[1]['x-api-key'],'secret')
            self.settings.save({'provider':'ollama','profiles':{'ollama':{'model':'translategemma:12b'}}})
            translation.translate(self.settings,'これはテストです。','en',Event())
            self.assertIn('Japanese (ja) to English (en)',requests[-1][2]['messages'][0]['content'])
        finally:server.shutdown();server.server_close();thread.join()

    def test_codex_uses_existing_signin_and_isolated_translation(self):
        with patch.object(translation,'run_codex',return_value=(0,'Logged in using ChatGPT')) as command:
            result=translation.connect_codex(self.settings,Event())
            self.assertTrue(result['settings']['profiles']['codex']['connected']);self.assertEqual(command.call_count,1)
        self.settings.save({'provider':'codex'})
        def execute(args,cancelled,**kwargs):
            self.assertIn('--ignore-user-config',args);self.assertIn('read-only',args);self.assertIn('features.shell_tool=false',args)
            self.assertIn('English',kwargs['prompt'])
            Path(args[args.index('--output-last-message')+1]).write_text('{"source_language":"Japanese","translation":"Hello"}')
            return 0,''
        with patch.object(translation,'run_codex',side_effect=execute):self.assertEqual(translation.translate(self.settings,'こんにちは','en',Event())['translation'],'Hello')
        self.settings.set_codex(False)
        with self.assertRaisesRegex(ValueError,'Connect'):translation.translate(self.settings,'こんにちは','en',Event())

    def test_plain_text_and_invalid_requests(self):
        detected={'name':'Japanese'}
        self.assertEqual(translation.parse_translation('Hello',detected)['translation'],'Hello')
        self.assertEqual(translation.parse_translation('```json\n{"translation":"Hello"}\n```',detected)['source_language'],'Japanese')
        for text in ('',' '*3,'a'*50001):
            with self.assertRaises(ValueError):translation.translate(self.settings,text,'en',Event())
        event=Event();event.set()
        with self.assertRaisesRegex(ValueError,'Cancelled'):translation.translate(self.settings,'こんにちは','en',event)


if __name__=='__main__':unittest.main()
