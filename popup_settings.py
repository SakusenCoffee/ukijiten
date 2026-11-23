"""Native popup preferences; dictionary selection and ordering are independent."""
import json
import re
from pathlib import Path

DEFAULTS=dict(section_states={},main_collapsed_paths=[],opacity=100,background_color='#141414',enabled=True,scan_delay=60,scan_length=24,scan_hotkey=[],
              popup_width=480,popup_height=410,disabled_paths=[],dictionary_order=[],frequency_paths=[],pitch_paths=[],main_frequency_paths=[],main_pitch_paths=[],frequency_order=[],pitch_order=[],main_frequency_order=[],main_pitch_order=[])

class PopupSettings:
    def __init__(self,path,dictionaries,legacy_path=None,browser_options=None):
        self.path=Path(path)
        def read(path):
            try:return json.loads(Path(path).read_text()) if path else {}
            except (OSError,ValueError,TypeError):return {}
        saved=read(self.path)
        if not saved:
            saved=read(legacy_path)
            browser=read(browser_options)
            if browser.get('profiles'):
                options=browser['profiles'][browser.get('profileCurrent',0)]['options']
                titles=[row[1] for row in dictionaries]
                names={title if titles.count(title)==1 else f'{title} [{did}]':p for did,title,p,_ in dictionaries}
                choices=options.get('dictionaries',[])
                saved['dictionary_order']=[names[d['name']] for d in choices if d['name'] in names]
                saved['disabled_paths']=[names[d['name']] for d in choices if d['name'] in names and not d['enabled']]
                general=options.get('general',{});scanning=options.get('scanning',{})
                saved.update(enabled=general.get('enable',True),popup_width=general.get('popupWidth',480),popup_height=general.get('popupHeight',410),scan_delay=scanning.get('delay',180),scan_length=scanning.get('length',24))
                inputs=[i for i in scanning.get('inputs',[]) if i.get('types',{}).get('mouse')]
                if inputs:
                    mapping={'ctrl':'Control','shift':'Shift','alt':'Alt','meta':'Meta','mouse0':'Mouse0','mouse1':'Mouse1','mouse2':'Mouse2','mouse3':'Mouse3','mouse4':'Mouse4'}
                    saved['scan_hotkey']=[mapping.get(k,k) for k in inputs[0].get('include','').split()]
        self.values={**DEFAULTS,**{k:v for k,v in saved.items() if k in DEFAULTS}}
        if 'dictionary_order' not in saved:self.values['dictionary_order']=[p for _,_,p,_ in dictionaries]
        if 'disabled_paths' not in saved:self.values['disabled_paths']=[p for _,_,p,enabled in dictionaries if not enabled]
        if 'scan_hotkey' not in saved:self.values['scan_hotkey']=['Shift'] if saved.get('shift_required') else []
        for _,_,path,_ in dictionaries:
            if path not in self.values['dictionary_order']:self.values['dictionary_order']=[*self.values['dictionary_order'],path]
        if 'pitch_paths' not in saved:self.values['pitch_paths']=[p for _,title,p,_ in dictionaries if 'nhk' in title.lower()]
        for key in ('main_frequency_paths','main_pitch_paths'):
            if key not in saved:self.values[key]=list(self.values[key.removeprefix('main_')])
        for key in ('scan_hotkey','dictionary_order','disabled_paths','frequency_paths','pitch_paths','main_frequency_paths','main_pitch_paths','frequency_order','pitch_order','main_frequency_order','main_pitch_order','main_collapsed_paths'):
            self.values[key]=list(dict.fromkeys(x for x in self.values[key] if isinstance(x,str)))

        self.values['section_states']={key:value for key,value in self.values['section_states'].items() if isinstance(key,str) and isinstance(value,bool)} if isinstance(self.values['section_states'],dict) else {}

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(self.values,ensure_ascii=False,indent=2));temporary.replace(self.path)

    def update(self,key,value):
        if key=='dictionary':
            disabled=set(self.values['disabled_paths'])
            if value['enabled']:disabled.discard(value['path'])
            else:disabled.add(value['path'])
            self.values['disabled_paths']=sorted(disabled)
        elif key in ('dictionary_order','scan_hotkey','frequency_paths','pitch_paths','main_frequency_paths','main_pitch_paths','frequency_order','pitch_order','main_frequency_order','main_pitch_order','main_collapsed_paths') and isinstance(value,list):
            self.values[key]=list(dict.fromkeys(v for v in value if isinstance(v,str)))
        elif key in ('scan_delay','scan_length','popup_width','popup_height'):
            low,high={'scan_delay':(0,2000),'scan_length':(1,48),'popup_width':(280,1200),'popup_height':(180,1000)}[key]
            self.values[key]=max(low,min(high,int(value)))
        elif key=='section_states' and isinstance(value,dict):self.values[key]={k:v for k,v in value.items() if isinstance(k,str) and isinstance(v,bool)}
        elif key=='opacity':self.values[key]=max(0,min(100,int(value)))
        elif key=='background_color' and re.fullmatch(r'#[0-9a-fA-F]{6}',str(value)):self.values[key]=value
        elif key=='enabled':self.values[key]=bool(value)
        else:return
        self.save()

    def metadata_selection(self,prefix=''):
        result=[]
        for kind in ('frequency','pitch'):
            paths=self.values[prefix+kind+'_paths']
            order={path:i for i,path in enumerate(self.values[prefix+kind+'_order'])}
            result.append(tuple(sorted(paths,key=lambda path:order.get(path,len(order)))))
        return tuple(result)

    def enabled_ids(self,dictionaries):
        disabled=set(self.values['disabled_paths']);order={p:i for i,p in enumerate(self.values['dictionary_order'])}
        return [did for did,_,p,_ in sorted(dictionaries,key=lambda row:order.get(row[2],len(order))) if p not in disabled]
