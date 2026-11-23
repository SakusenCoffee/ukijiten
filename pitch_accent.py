"""Read NHK pronunciation metadata even when its definition dictionary is disabled."""
from collections import OrderedDict
import html
import json
import re
import unicodedata


def hiragana(text):
    return ''.join(chr(ord(c)-0x60) if '\u30a1' <= c <= '\u30f6' else c
                   for c in unicodedata.normalize('NFKC', text))


def morae(text):
    result=[]
    for c in unicodedata.normalize('NFC',text):
        if c in 'ァィゥェォャュョヮヵヶぁぃぅぇぉゃゅょゎゕゖ' and result:
            result[-1]+=c
        elif unicodedata.category(c).startswith('L'):
            result.append(c)
    return result


def accent_signatures(node):
    if isinstance(node,list):
        for child in node:yield from accent_signatures(child)
    elif isinstance(node,dict):
        data=node.get('data',{})
        if data.get('pitchAccentText') and isinstance(data.get('accentSig'),str):
            yield data['accentSig']
        else:
            yield from accent_signatures(node.get('content',[]))


def parse_accents(glossary):
    variants=[]
    for signature in accent_signatures(json.loads(glossary)):
        for accent in re.split(r'\s*\|\s*|\s+/\s+',signature):
            if '＼' in accent:
                before,after=accent.split('＼',1)
                position=len(morae(before))
                reading=''.join(morae(before+after))
            elif any(mark in accent for mark in ('━','￣')):
                position=0
                reading=''.join(morae(accent))
            else:
                continue  # Never guess an accent from an unmarked/unknown format.
            parts=morae(reading)
            value=(tuple(parts),position)
            if parts and position<=len(parts) and value not in variants:
                variants.append(value)
    return variants


def high(index, position):
    return index==0 if position==1 else index>0 and (position==0 or index<position)


def render_variant(parts, position):
    word=''.join(parts)
    labels=[]
    for i,mora in enumerate(parts):
        classes='pitch-mora'+(' pitch-high' if high(i,position) else '')+(' pitch-drop' if high(i,position) and not high(i+1,position) else '')
        labels.append(f'<span class="{classes}">{html.escape(mora)}</span>')
    points=[(8+i*13,5 if high(i,position) else 19) for i in range(len(parts)+1)]
    line=' '.join(f'{x},{y}' for x,y in points[:-1])
    x,y=points[-1];previous=points[-2]
    dots=''.join(f'<circle cx="{px}" cy="{py}" r="2.6"/>' for px,py in points[:-1])
    graph=f'<svg class="pitch-graph" width="{x+7}" height="24" viewBox="0 0 {x+7} 24" aria-hidden="true"><polyline points="{line}"/><path class="pitch-tail" d="M{previous[0]} {previous[1]} L{x} {y}"/>{dots}<path class="pitch-particle" d="M{x-3} {y-3} L{x+3} {y-3} L{x} {y+3} Z"/></svg>'
    return f'<span class="pitch-variant" title="{html.escape(word)} [{position}]"><span class="pitch-word" lang="ja">'+''.join(labels)+f'</span><span class="pitch-position">[{position}]</span>{graph}</span>'


class PitchAccents:
    def __init__(self, database):
        self.db=database
        self.cache=OrderedDict()
        self.signature=None

    def rows(self, entries):
        dictionaries=self.db.execute("SELECT id,title FROM dictionaries WHERE lower(title) LIKE '%nhk%' ORDER BY id").fetchall()
        signature=(tuple(dictionaries),self.db.execute('PRAGMA data_version').fetchone()[0])
        if signature!=self.signature:
            self.signature=signature;self.cache.clear()
        if not dictionaries:return {}
        ids=[row[0] for row in dictionaries]
        slots=','.join('?' for _ in ids)
        output={}
        for term,reading,*_ in entries:
            key=(term,hiragana(reading))
            if key not in self.cache:
                variants=[]
                rows=self.db.execute(f'SELECT reading,glossary FROM entries INDEXED BY entries_term WHERE term=? AND dictionary_id IN ({slots}) LIMIT 40',(term,*ids)).fetchall()
                for source_reading,glossary in rows:
                    if reading and hiragana(source_reading)!=key[1]:continue
                    try:
                        for variant in parse_accents(glossary):
                            if variant not in variants:variants.append(variant)
                    except (ValueError,TypeError):continue
                label='<span class="pitch-badge">NHK</span>'
                body=''.join(render_variant(*variant) for variant in variants)
                if not body:body='<span class="pitch-unavailable" title="No matching NHK pitch data">—</span>'
                self.cache[key]='<div class="pitch-row" aria-label="NHK pitch accent">'+label+body+'</div>'
                if len(self.cache)>2048:self.cache.popitem(last=False)
            else:self.cache.move_to_end(key)
            output[(term,reading)]=self.cache[key]
        return output
