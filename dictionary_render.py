"""Render Yomitan structured definitions with a restricted HTML vocabulary."""
import html
import re
import json
import sys
from lookup_cache import ByteCache

_definitions = ByteCache(max_bytes=8 * 1024 * 1024, max_entries=512)


def render_definition(glossary):
    cached = _definitions.get(glossary)
    if cached is not None:
        return cached
    output = render(json.loads(glossary))
    _definitions.put(glossary, output, sys.getsizeof(glossary) + sys.getsizeof(output))
    return output

def render(node):
    if isinstance(node, str):
        return html.escape(node).replace('\n', '<br>')
    if isinstance(node, list):
        return ''.join(render(item) for item in node)
    if not isinstance(node, dict):
        return html.escape(str(node))
    if node.get('type') == 'structured-content':
        return render(node.get('content', ''))
    if node.get('type') == 'image':
        return '<span class="media">[image: ' + html.escape(str(node.get('path', ''))) + ']</span>'
    if node.get('type') in ('audio', 'pronunciation'):
        return '<span class="media">[audio]</span>'
    tag = node.get('tag', 'span')
    if tag not in {'div','span','p','br','b','strong','i','em','ul','ol','li','ruby','rt','rp','table','thead','tbody','tr','td','th','a','sup','sub','small','blockquote'}:
        tag = 'span'
    if tag == 'br':
        return '<br>'
    styles = node.get('style', {})
    safe = []
    if isinstance(styles, dict):
        for key, val in styles.items():
            if key in {'fontWeight','fontStyle','textDecoration','color','backgroundColor','fontSize','textAlign'} and re.fullmatch(r'[\w#().,%\s-]{1,60}', str(val)):
                css_key = re.sub(r'([A-Z])', lambda m: '-' + m[1].lower(), key)
                safe.append(f'{css_key}:{val}')
    attrs = ' style="' + ';'.join(safe) + '"' if safe else ''
    data=node.get('data',{})
    if isinstance(data,dict) and any('example' in str(key).lower() or 'example' in str(value).lower() for key,value in data.items()):attrs+=' class="example-sentence"'
    if tag == 'a':
        href = node.get('href', '')
        if isinstance(href, str) and href.startswith('?query='):
            attrs += ' href="' + html.escape(href, quote=True) + '"'
    return f'<{tag}{attrs}>' + render(node.get('content', '')) + f'</{tag}>'


