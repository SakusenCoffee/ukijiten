"""Read-only, selected-deck graphs and vocabulary kanji from Anki snapshots/API."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
import json
from functools import lru_cache
from pathlib import Path
import re
import shlex
import sqlite3
import unicodedata
from anki_stats import anki_request
from study_day import study_date,validate_cutoff


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.hidden=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','rt','rp'): self.hidden+=1
    def handle_endtag(self, tag):
        if tag in ('script','style','rt','rp'): self.hidden=max(0,self.hidden-1)
    def handle_data(self, value):
        if not self.hidden:self.parts.append(value)


def kanji_characters(value):
    parser=PlainText();parser.feed(str(value))
    text=re.sub(r'\[sound:[^\]]*\]', '', unescape(''.join(parser.parts)))
    return {char for char in text if unicodedata.name(char,'').startswith(('CJK UNIFIED IDEOGRAPH','CJK COMPATIBILITY IDEOGRAPH'))}


JOYO_ALIASES={'剥':'剝','頬':'頰','填':'塡','叱':'𠮟'}

@lru_cache(maxsize=1)
def kanji_catalog():
    data=json.loads((Path(__file__).parent/'assets/kanji_catalog.json').read_text())
    if len(data['joyo'])!=2136 or len(set(data['joyo']))!=2136:
        raise ValueError('Invalid Jōyō character catalog.')
    return data


def kanji_options():
    """Start with the installed Kanji Grid's interval, fields and display choices."""
    config={}
    home=Path.home()
    for root in (home/'.var/app/net.ankiweb.Anki/data/Anki2/addons21',home/'.local/share/Anki2/addons21',home/'Library/Application Support/Anki2/addons21'):
        for folder in sorted(root.glob('*')):
            try:
                meta=json.loads((folder/'meta.json').read_text())
                if 'kanji grid' not in meta.get('name','').lower():continue
                config=json.loads((folder/'config.json').read_text());config.update(meta.get('config',{}));break
            except (OSError,ValueError,TypeError):continue
        if config:break
    return clean_kanji_preferences({
        'fields':shlex.split(str(config.get('defaultfield','')).lower()),
        'interval':config.get('interval',180),'show_unseen':bool(config.get('unseen',True)),
        'tooltips':bool(config.get('tooltips',True)),
        'sort':{0:'original',1:'unicode',2:'score',3:'seen',4:'unseen'}.get(config.get('sortby',2),'score')})


def clean_kanji_preferences(values, defaults=None):
    result=dict(defaults or {'fields':[],'interval':180,'show_unseen':True,'show_missing':True,
        'tooltips':True,'show_other':True,'sort':'score','group':'none','deck':'combined','tile_size':30,'palette':'dark',
        'text_color':'automatic','options_open':False})
    if not isinstance(values,dict):raise ValueError('Invalid kanji grid options.')
    for key,value in values.items():
        if key not in result:continue
        if key in ('interval','tile_size'):
            if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError('Invalid grid size or interval.')
            lo,hi=(1,65536) if key=='interval' else (18,60)
            if not lo<=value<=hi:raise ValueError('Grid size or interval is out of range.')
            value=int(value)
        elif key in ('show_unseen','show_missing','show_other','tooltips','options_open'):
            if type(value) is not bool:raise ValueError('Invalid grid switch.')
        elif key=='deck':
            if not isinstance(value,str) or len(value)>512 or (value!='combined' and not value.startswith('deck:')):raise ValueError('Invalid kanji deck selection.')
        elif key=='fields':
            if not isinstance(value,list) or len(value)>64 or any(not isinstance(field,str) or len(field)>128 for field in value):raise ValueError('Invalid kanji fields.')
            value=list(dict.fromkeys(field.strip().lower() for field in value if field.strip()))
        elif value not in {'sort':('score','unicode','seen','unseen','original'),'group':('none','grade','jlpt','decks'),
                          'palette':('dark','kanjigrid','blue'),'text_color':('automatic','black','white')}[key]:
            raise ValueError('Invalid kanji grid option.')
        result[key]=value
    return result


def target_deck(name, targets):
    normalized=name.replace('\x1f','::').replace(' ','').casefold()
    for target in sorted(targets,key=len,reverse=True):
        key=target.replace(' ','').casefold()
        if normalized==key or normalized.startswith(key+'::'):return target
    return None


def _field_names(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='fields'").fetchone():
        result=defaultdict(dict)
        for mid,ordinal,name in db.execute('SELECT ntid,ord,name FROM fields'):result[mid][ordinal]=name
        return result
    try:
        models=json.loads(db.execute('SELECT models FROM col').fetchone()[0])
        return {int(mid):{i:field['name'] for i,field in enumerate(model['flds'])} for mid,model in models.items()}
    except (sqlite3.Error,ValueError,TypeError):return {}


def read_collection(path, targets):
    db=sqlite3.connect(Path(path).expanduser().resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    db.create_collation('unicase',lambda a,b:(a.casefold()>b.casefold())-(a.casefold()<b.casefold()))
    try:
        db.execute('BEGIN')
        decks={did:target_deck(name,targets) for did,name in db.execute('SELECT id,name FROM decks')}
        cards={}
        for row in db.execute('SELECT id,nid,did,odid,mod,type,queue,ivl,reps,lapses FROM cards'):
            cid,nid,did,odid,modified,kind,queue,interval,reps,lapses=row
            cards[cid]={'id':cid,'note':nid,'deck':decks.get(odid or did),'mod':modified,'type':kind,'queue':queue,
                        'interval':interval,'reps':reps,'lapses':lapses,'fields':{}}
        names=_field_names(db)
        note_ids=sorted({card['note'] for card in cards.values() if card['deck']})
        notes={}
        for offset in range(0,len(note_ids),400):
            batch=note_ids[offset:offset+400];marks=','.join('?' for _ in batch)
            for nid,mid,fields in db.execute('SELECT id,mid,flds FROM notes WHERE id IN ('+marks+')',batch):
                notes[nid]={names.get(mid,{}).get(i,'Field '+str(i+1)):value for i,value in enumerate(fields.split('\x1f'))}
        for card in cards.values():card['fields']=notes.get(card['note'],{})
        selected=[cid for cid,card in cards.items() if card['deck']]
        reviews={}
        for offset in range(0,len(selected),400):
            batch=selected[offset:offset+400];marks=','.join('?' for _ in batch)
            for identifier,cid,ease,interval,previous,milliseconds,kind in db.execute(
                    'SELECT id,cid,ease,ivl,lastIvl,time,type FROM revlog WHERE cid IN ('+marks+')',batch):
                reviews[identifier]={'id':identifier,'card':cid,'ease':ease,'interval':interval,'previous':previous,
                                     'milliseconds':max(0,milliseconds),'type':kind}
        return cards,reviews
    finally:db.close()


def read_connect(config):
    cards={};reviews={};assignments={}
    # Longest parent/subdeck match wins, including cards temporarily in filtered decks.
    for deck in sorted(config['decks'],key=len,reverse=True):
        escaped=deck.replace('\\','\\\\').replace('"','\\"')
        for cid in anki_request(config,'findCards',query='deck:"'+escaped+'"'):assignments.setdefault(cid,deck)
    ids=list(assignments)
    for offset in range(0,len(ids),300):
        batch=ids[offset:offset+300]
        # Avoid generating question/answer HTML and CSS for thousands of cards.
        try:
            infos=anki_request(config,'cardsInfo',cards=batch,
                fields=['cardId','note','fields','type','queue','interval','reps','lapses','mod'])
        except ValueError as error:
            if 'fields' not in str(error) or 'unexpected' not in str(error).lower():raise
            infos=anki_request(config,'cardsInfo',cards=batch)
        for info in infos:
            cid=int(info['cardId'])
            fields={name:value.get('value','') for name,value in sorted(info.get('fields',{}).items(),key=lambda item:item[1].get('order',0))}
            cards[cid]={'id':cid,'note':info['note'],'deck':assignments[cid],'mod':info.get('mod',0),
                        'type':info.get('type',0),'queue':info.get('queue',0),'interval':info.get('interval',0),
                        'reps':info.get('reps',0),'lapses':info.get('lapses',0),'fields':fields}
        histories=anki_request(config,'getReviewsOfCards',cards=batch)
        for cid,history in histories.items():
            for item in history:
                identifier=int(item['id'])
                reviews[identifier]={'id':identifier,'card':int(cid),'ease':item.get('ease',0),'interval':item.get('ivl',0),
                                     'previous':item.get('lastIvl',0),'milliseconds':max(0,item.get('time',0)),'type':item.get('type',1)}
    return cards,reviews


def summarize(cards, reviews, *, deck, today, options, cutoff_hour=0):
    days={};answers=[0,0,0,0];hourly=[0]*24;first={}
    for review in reviews:
        # ease=0 logs rescheduling/manual changes, not a remembered/forgotten answer.
        ease=int(review['ease'])
        if ease not in (1,2,3,4):continue
        stamp=datetime.fromtimestamp(review['id']/1000).astimezone();day=study_date(stamp,cutoff_hour).isoformat()
        record=days.setdefault(day,{'reviews':0,'seconds':0,'retention_total':0,'retention_pass':0,'first':0})
        record['reviews']+=1;record['seconds']+=review['milliseconds']/1000
        answers[ease-1]+=1;hourly[stamp.hour]+=1
        first[review['card']]=min(first.get(review['card'],day),day)
        if review['type']==1:
            record['retention_total']+=1;record['retention_pass']+=int(ease>1)
    for day in first.values():days[day]['first']+=1
    stages=Counter();intervals=[0]*6;kanji=defaultdict(lambda:{'seen':0,'unseen':0,'sum_interval':0.0})
    used_fields=set()
    for card in cards:
        kind,queue,interval=card['type'],card['queue'],max(0,float(card['interval']))
        stage='Suspended' if queue==-1 else 'New' if kind==0 else 'Learning' if kind in (1,3) else 'Mature' if interval>=21 else 'Young'
        stages[stage]+=1
        if kind==2 and queue!=-1:
            index=next((i for i,upper in enumerate((1,7,21,90,365,float('inf'))) if interval<=upper),5)
            intervals[index]+=1
        fields=card['fields']
        wanted=options['fields'] or [next(iter(fields),'').lower()]
        text=[]
        for name,value in fields.items():
            if name.lower() in wanted:used_fields.add(name);text.append(value)
        for char in {JOYO_ALIASES.get(char,char) for char in kanji_characters(' '.join(text))}:
            cell=kanji[char]
            if kind>0:cell['seen']+=1;cell['sum_interval']+=interval
            else:cell['unseen']+=1
    cells=[]
    for char,cell in kanji.items():
        average=cell['sum_interval']/max(1,cell['seen'])
        strength=1-1/(1+average/options['interval'])**2 if cell['seen'] else 0
        cells.append({'char':char,'seen':cell['seen'],'unseen':cell['unseen'],'interval':round(average,1),'strength':round(strength,4)})
    cells.sort(key=lambda cell:(-cell['strength'],-cell['seen'],cell['char']))
    return {'deck':deck,'cards':len(cards),'days':days,'answers':answers,'hourly':hourly,
            'stages':[stages[name] for name in ('New','Learning','Young','Mature','Suspended')],
            'intervals':intervals,'kanji':cells,'fields':sorted(used_fields)}


def load_insights(config, *, today=None, options=None, cutoff_hour=0):
    if not config.get('enabled'):raise ValueError('Enable Anki in Stats settings.')
    targets=list(dict.fromkeys(config.get('decks',[])))
    if not targets:raise ValueError('Select Anki decks in Stats settings.')
    cutoff_hour=validate_cutoff(cutoff_hour)
    today=today or study_date(cutoff=cutoff_hour);options=clean_kanji_preferences(options) if options is not None else kanji_options()
    if config.get('backend')=='connect':cards,reviews=read_connect(config)
    else:
        cards={};reviews={};readable=False
        for path in config.get('paths',[]):
            try:incoming,history=read_collection(path,targets)
            except (sqlite3.Error,OSError,ValueError):continue
            readable=True
            for cid,card in incoming.items():
                if cid not in cards or card['mod']>=cards[cid]['mod']:cards[cid]=card
            reviews.update(history)
        if not readable:raise ValueError('Cannot read the selected Anki collection files.')
    cards={cid:card for cid,card in cards.items() if card['deck'] in targets}
    reviews=[review for review in reviews.values() if review['card'] in cards]
    if not config.get('include_time',True):reviews=[{**review,'milliseconds':0} for review in reviews]
    per_deck=[]
    for target in targets:
        selected=[card for card in cards.values() if card['deck']==target]
        per_deck.append(summarize(selected,[review for review in reviews if cards[review['card']]['deck']==target],deck=target,today=today,options=options,cutoff_hour=cutoff_hour))
    return {'combined':summarize(list(cards.values()),reviews,deck='Combined',today=today,options=options,cutoff_hour=cutoff_hour),
            'decks':per_deck,'date':today.isoformat(),'interval':options['interval'],
            'catalog':kanji_catalog(),'options':options,
            'available_fields':sorted({name for card in cards.values() for name in card['fields']},key=str.casefold)}
