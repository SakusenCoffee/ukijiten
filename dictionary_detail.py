"""Character detail lookup for the main dictionary panes."""
from pathlib import Path
from threading import Event
from character_lookup import lookup_character


def lookup_detail(path, kind, payload):
    if kind != 'character':return ''
    return lookup_character(str(payload.get('character','')),Event(),Path(path))
