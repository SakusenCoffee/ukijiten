"""Entry font choices shared by the main dictionary and scan popup."""
import re
from PySide6.QtGui import QFontDatabase


FONT_GROUPS = (
    ('Japanese', (
        'Noto Sans CJK JP', 'Noto Sans JP', 'Noto Serif CJK JP', 'Noto Serif JP',
        'Source Han Sans JP', 'Source Han Serif JP', 'Yu Gothic', 'Yu Mincho',
        'Meiryo', 'Hiragino Sans', 'Hiragino Kaku Gothic ProN',
        'Hiragino Mincho ProN', 'MS PGothic', 'MS PMincho', 'IPAGothic', 'IPAMincho',
    )),
    ('Rounded & handwritten', (
        'Zen Maru Gothic', 'Yomogi', 'Hachi Maru Pop', 'KouzanBrushFontGyousyoOTF',
    )),
    ('Chinese · Simplified', (
        'Noto Sans CJK SC', 'Noto Serif CJK SC', 'Noto Sans SC', 'Noto Serif SC',
        'Source Han Sans SC', 'Source Han Serif SC', 'Microsoft YaHei',
        'SimSun', 'SimHei', 'KaiTi', 'FangSong', 'PingFang SC', 'Songti SC',
    )),
    ('Chinese · Traditional', (
        'Noto Sans CJK TC', 'Noto Serif CJK TC', 'Noto Sans CJK HK', 'Noto Serif CJK HK',
        'Noto Sans TC', 'Noto Serif TC', 'Source Han Sans TC', 'Source Han Serif TC',
        'Microsoft JhengHei', 'PMingLiU', 'MingLiU', 'DFKai-SB', 'PingFang TC', 'Songti TC',
    )),
)
BUNDLED_FONTS = {'Zen Maru Gothic', 'Yomogi', 'Hachi Maru Pop'}


def normalize_font(value):
    # Stored as a family name, independent of language or a future dictionary profile.
    return value if isinstance(value, str) and len(value) <= 160 and not any(
        ord(char) < 32 for char in value) else ''


def font_choices():
    # Qt appends foundry names when several packages provide the same family.
    # CSS/fontconfig uses the plain family name, e.g. Noto Sans CJK JP.
    installed = {re.sub(r' \[[^\]]+\]$', '', family) for family in QFontDatabase.families()}
    available = installed | BUNDLED_FONTS
    groups = []
    used = set()
    for label, families in FONT_GROUPS:
        choices = [family for family in families if family in available]
        if choices:
            groups.append({'label': label, 'families': choices})
            used.update(choices)
    others = sorted(installed - used, key=str.casefold)
    if others:
        groups.append({'label': 'Other installed fonts', 'families': others})
    return groups
