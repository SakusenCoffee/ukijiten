"""Browser-only cloud setup. No native progress or credential dialogs."""
import json
import secrets
import subprocess
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal
from cloud_dialog import browser_answer
from mokuro_cloud import (binary, config_command, connect_mega, identify_account,
                          connection_update, connection_summary, PROVIDERS)

PAGE='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect account</title>
<style>body{font:16px system-ui;background:#161b20;color:#e7edf1;margin:0;padding:48px 20px}main{max-width:440px;margin:auto}h1{font-size:25px}label{display:grid;gap:7px;margin:20px 0}input,select,button{font:inherit;padding:12px;border-radius:8px;border:1px solid #59626b;background:#222b32;color:inherit}button{cursor:pointer}button[type=submit]{background:#346e93}p{line-height:1.5}#status{color:#afd8e9}</style></head><body><main><h1 id="title">Connect account</h1><p id="message"></p><form id="form"></form><p id="status" role="status"></p></main><script>
const title=document.getElementById('title'),message=document.getElementById('message'),form=document.getElementById('form'),status=document.getElementById('status');
let generation='';
async function poll(){try{const response=await fetch(location.pathname+'state',{cache:'no-store'}),state=await response.json();
if(state.done){title.textContent=state.success?'Connected':'Connection closed';message.textContent=state.success?'You can close this window and return to the dictionary.':state.message;form.replaceChildren();return;}
if(generation!==state.generation){generation=state.generation;status.textContent='';title.textContent=state.title;message.textContent=state.message||'';form.replaceChildren();
for(const field of state.fields||[]){const label=document.createElement('label'),caption=document.createElement('span');caption.textContent=field.label;const input=document.createElement(field.choices?'select':'input');input.name=field.name;
if(field.choices){for(const choice of field.choices){const option=document.createElement('option');option.value=choice.value;option.textContent=choice.label;input.append(option);}}else{input.type=field.type||'text';input.required=!!field.required;input.value=field.value||'';input.autocomplete=field.type==='password'?'current-password':field.type==='email'?'username':'off';}label.append(caption,input);form.append(label);}
const submit=document.createElement('button');submit.type='submit';submit.textContent=state.submit||'Continue';form.append(submit);
form.onsubmit=async event=>{event.preventDefault();if(!form.reportValidity())return;submit.disabled=true;status.textContent='Connecting…';const values=Object.fromEntries(new FormData(form));await fetch(location.pathname+'answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({generation,...values})});form.querySelectorAll('input[type=password]').forEach(input=>input.value='');};}
}catch(e){}setTimeout(poll,500);}poll();
</script></body></html>'''


class BrowserCloudConnection(QObject):
    finished=Signal(str,bool)

    def __init__(self,directory,provider,parent=None):
        super().__init__(parent)
        self.directory,self.provider=directory,provider
        self.closed=False;self.process=None;self.server=None;self.browser_page_open=False
        self.condition=threading.Condition();self.answer=None
        self.page_state={};self.token=secrets.token_urlsafe(32)
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='cloud-connect')
        self.future=None

    def start(self):
        connection_update(self.directory,self.provider,state='connecting')
        self.future=self.pool.submit(self.run)
        self.future.add_done_callback(self.completed)

    def completed(self,future):
        if self.closed:return
        try:success=future.result()
        except Exception:success=False
        if not self.closed:self.finished.emit(self.provider,success)

    def command(self,args,timeout=300):
        if self.closed:raise RuntimeError('Cancelled')
        self.process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:stdout,_=self.process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill();self.process.communicate();raise ValueError('Sign-in timed out. Press Refresh to try again.') from None
        if self.closed:raise RuntimeError('Cancelled')
        if self.process.returncode:raise ValueError('Sign-in failed. Check the account and try again.')
        return stdout

    def request(self,title,fields,message='',submit='Continue'):
        if self.server is None:self.start_server()
        generation=secrets.token_hex(8)
        with self.condition:
            self.answer=None;self.page_state=dict(generation=generation,title=title,fields=fields,message=message,submit=submit)
        if not self.browser_page_open:
            webbrowser.open(self.address,new=1)
            self.browser_page_open=True
        with self.condition:
            self.condition.wait_for(lambda:self.answer is not None or self.closed,timeout=300)
            if self.closed or self.answer is None:raise ValueError('Sign-in was not completed.')
            return self.answer

    def start_server(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in (owner.route,owner.route+'state'):
                    self.send_error(404);return
                data=PAGE.encode() if self.path==owner.route else json.dumps(owner.page_state).encode()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8' if self.path==owner.route else 'application/json')
                self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY');self.end_headers();self.wfile.write(data)
            def do_POST(self):
                if self.path!=owner.route+'answer':self.send_error(404);return
                origin=self.headers.get('Origin','')
                if origin and origin!=owner.origin:self.send_error(403);return
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=16384:raise ValueError()
                    values=json.loads(self.rfile.read(length))
                    if values.get('generation')!=owner.page_state.get('generation'):raise ValueError()
                except (ValueError,TypeError):self.send_error(400);return
                with owner.condition:owner.answer=values;owner.condition.notify_all()
                self.send_response(204);self.end_headers()
            def log_message(self,*_):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True
        self.route='/'+self.token+'/'
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.address=self.origin+self.route
        threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.1),daemon=True).start()

    def run(self):
        success=False
        try:
            binary(self.directory,install=True)
            if self.provider=='mega':
                values=self.request('Sign in to MEGA',[
                    {'name':'email','label':'Email','type':'email','required':True,'value':connection_summary(self.directory)['mega'].get('account','')},
                    {'name':'password','label':'Password','type':'password','required':True},
                    {'name':'code','label':'Two-factor code (optional)','type':'text'}],submit='Sign in')
                connect_mega(self.directory,values['email'],values['password'],values.get('code',''),is_cancelled=lambda:self.closed)
                values.clear()
            else:
                command=config_command(self.directory,self.provider)
                for _ in range(60):
                    data=json.loads(self.command(command))
                    if not data.get('State'):
                        if data.get('Error'):raise ValueError('Sign-in failed. Please try again.')
                        break
                    option=data.get('Option') or {};name=option.get('Name','');answer=browser_answer(name)
                    if name in ('config_token','config_verification_code') or (name in ('client_id','client_secret') and option.get('Required')):
                        raise ValueError('Browser sign-in did not complete. Press Refresh to try again.')
                    choose=name.startswith(('config_drive','config_type','config_team_drive'))
                    if answer is None and (option.get('Required') or choose or data.get('Error')):
                        examples=option.get('Examples') or []
                        if len(examples)==1:answer=str(examples[0]['Value'])
                        else:
                            field={'name':'value','label':'Storage','required':bool(option.get('Required'))}
                            if examples:field['choices']=[{'value':str(item['Value']),'label':str(item.get('Help') or item['Value'])} for item in examples]
                            response=self.request('Choose your '+PROVIDERS[self.provider][0]+' storage',[field])
                            answer=response.get('value','')
                    if answer is None:
                        default=option.get('Default');answer='true' if default is True else 'false' if default is False else str(default or '')
                    command=config_command(self.directory,self.provider,data['State'],answer)
                else:raise ValueError('Connection setup did not finish.')
            if self.closed:return False
            try:account=identify_account(self.directory,self.provider)
            except Exception:account=''
            connection_update(self.directory,self.provider,if_active=lambda:not self.closed,state='connected',account=account)
            success=True
        except Exception as error:
            if not self.closed:connection_update(self.directory,self.provider,if_active=lambda:not self.closed,state='needs_auth',message=str(error) if isinstance(error,ValueError) else 'Sign-in was not completed.')
        finally:
            self.answer=None
            self.page_state={'done':True,'success':success,'message':'Sign-in was not completed. Return to the dictionary to retry.'}
        return success

    def close(self):
        self.closed=True
        with self.condition:self.condition.notify_all()
        if self.process and self.process.poll() is None:
            self.process.kill()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:pass
        if self.server:
            self.server.shutdown();self.server.server_close()
        self.pool.shutdown(wait=False,cancel_futures=True)
