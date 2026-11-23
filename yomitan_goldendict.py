#!/usr/bin/env python3
"""A fast desktop reader for Yomitan dictionary ZIP archives."""
import html
from itertools import islice, product
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import parse_qs
import zipfile

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt, QUrl, QSize
from PySide6.QtGui import QAction, QKeySequence, QDesktopServices, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QSplitter, QTabWidget, QTextBrowser, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, QStyledItemDelegate, QStyleOptionViewItem, QStyle)

APP_DIR = Path.home() / '.local/share/yomitan-goldendict'
DB_PATH = APP_DIR / 'dictionaries.sqlite3'
COLLECTION = Path(os.environ.get('UKIJITEN_DICTIONARIES',Path.home()/'Documents/Dictionaries'))

ROMAJI = dict(zip(
    ('a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to '
     'na ni nu ne no ha hi fu he ho ma mi mu me mo ya yu yo '
     'ra ri ru re ro wa wo ga gi gu ge go za ji zu ze zo '
     'da di du de do ba bi bu be bo pa pi pu pe po').split(),
    ('あ い う え お か き く け こ さ し す せ そ た ち つ て と '
     'な に ぬ ね の は ひ ふ へ ほ ま み む め も や ゆ よ '
     'ら り る れ ろ わ を が ぎ ぐ げ ご ざ じ ず ぜ ぞ '
     'だ ぢ づ で ど ば び ぶ べ ぼ ぱ ぴ ぷ ぺ ぽ').split()))
ROMAJI.update({'si':'し','ti':'ち','tu':'つ','hu':'ふ','zi':'じ','di':'じ','du':'ず',
               'ja':'じゃ','ju':'じゅ','jo':'じょ','sha':'しゃ','shu':'しゅ','sho':'しょ',
               'cha':'ちゃ','chu':'ちゅ','cho':'ちょ','she':'しぇ','che':'ちぇ','je':'じぇ',
               'tsa':'つぁ','tsi':'つぃ','tse':'つぇ','tso':'つぉ',
               'fa':'ふぁ','fi':'ふぃ','fe':'ふぇ','fo':'ふぉ',
               'va':'ゔぁ','vi':'ゔぃ','vu':'ゔ','ve':'ゔぇ','vo':'ゔぉ',
               'ye':'いぇ','wi':'うぃ','we':'うぇ','wu':'う',
               'ca':'か','ci':'し','cu':'く','ce':'せ','co':'こ','qu':'く',
               'xtu':'っ','xtsu':'っ','ltu':'っ','ltsu':'っ','xn':'ん',
               'tha':'てゃ','thi':'てぃ','thu':'てゅ','the':'てぇ','tho':'てょ',
               'dha':'でゃ','dhi':'でぃ','dhu':'でゅ','dhe':'でぇ','dho':'でょ',
               'twa':'とぁ','twi':'とぃ','twu':'とぅ','twe':'とぇ','two':'とぉ',
               'dwa':'どぁ','dwi':'どぃ','dwu':'どぅ','dwe':'どぇ','dwo':'どぉ',
               'qa':'くぁ','qi':'くぃ','qe':'くぇ','qo':'くぉ',
               'kwa':'くぁ','kwi':'くぃ','kwu':'くぅ','kwe':'くぇ','kwo':'くぉ',
               'gwa':'ぐぁ','gwi':'ぐぃ','gwu':'ぐぅ','gwe':'ぐぇ','gwo':'ぐぉ',
               'hwa':'ふぁ','hwi':'ふぃ','hwe':'ふぇ','hwo':'ふぉ',
               'whi':'うぃ','whu':'う','whe':'うぇ','who':'うぉ',
               'fya':'ふゃ','fyu':'ふゅ','fyo':'ふょ',
               'vya':'ゔゃ','vyu':'ゔゅ','vyo':'ゔょ'})
for stem, kana in {'ky':'き','sy':'し','shy':'し','ty':'ち','chy':'ち',
                   'ny':'に','hy':'ひ','my':'み','ry':'り','gy':'ぎ',
                   'zy':'じ','jy':'じ','j':'じ','by':'び','py':'ぴ','dy':'ぢ','cy':'ち'}.items():
    for vowel, small in {'a':'ゃ','u':'ゅ','o':'ょ'}.items():
        ROMAJI[stem + vowel] = kana + small
for prefix in ('x', 'l'):
    ROMAJI.update({prefix + k: v for k, v in {
        'a':'ぁ','i':'ぃ','u':'ぅ','e':'ぇ','o':'ぉ',
        'ya':'ゃ','yu':'ゅ','yo':'ょ','wa':'ゎ'}.items()})
for stem, kana in {'ky':'き','sy':'し','ty':'ち','ny':'に','hy':'ひ','my':'み',
                   'ry':'り','gy':'ぎ','zy':'じ','jy':'じ','by':'び','py':'ぴ',
                   'dy':'ぢ','cy':'ち'}.items():
    ROMAJI[stem + 'e'] = kana + 'ぇ'

AMBIGUOUS_ROMAJI = {'du': ('ず', 'づ'), 'di': ('じ', 'ぢ'),
                    'zi': ('じ', 'ぢ'), 'ji': ('じ', 'ぢ')}
LONG_VOWELS = {'ā': ('aa',), 'â': ('aa',), 'ī': ('ii',), 'î': ('ii',),
               'ū': ('uu',), 'û': ('uu',), 'ē': ('ee',), 'ê': ('ee',),
               'ō': ('ou', 'oo'), 'ô': ('ou', 'oo')}


def romaji_to_hiragana_variants(word):
    """Return distinct kana lookup keys for complete romaji."""
    word = word.lower()
    if not re.fullmatch(r"[a-z'āīūēōâîûêô]+", word):
        return ()
    spellings = ['']
    for char in word:
        spellings = [prefix + expansion for prefix in spellings
                     for expansion in LONG_VOWELS.get(char, (char,))][:16]
    results = []
    for spelling in spellings:
        results.extend(_ascii_romaji_variants(spelling))
    return tuple(dict.fromkeys(results))[:16]


def _ascii_romaji_variants(word):
    parts = []
    i = 0
    while i < len(word):
        char = word[i]
        following = word[i + 1] if i + 1 < len(word) else ''
        if char == 'm' and following in 'bp':
            parts.append(('ん',))
            i += 1
            continue
        if char == 'n':
            if following == "'":
                parts.append(('ん',))
                i += 2
                continue
            if following == 'n' and i + 2 == len(word):
                parts.append(('ん',))
                i += 2
                continue
            if not following or (following not in 'aeiouy' and following != 'n') or following == 'n':
                parts.append(('ん',))
                i += 1
                continue
        if char == following and char not in 'aeioun':
            parts.append(('っ',))
            i += 1
            continue
        if word[i:i + 3] == 'tch':
            parts.append(('っ',))
            i += 1
            continue
        size = next((size for size in (4, 3, 2, 1) if word[i:i + size] in ROMAJI), None)
        if size is None:
            return ()
        syllable = word[i:i + size]
        parts.append(AMBIGUOUS_ROMAJI.get(syllable, (ROMAJI[syllable],)))
        i += size
    return tuple(dict.fromkeys(''.join(pieces) for pieces in islice(product(*parts), 16)))


def romaji_to_hiragana(word):
    variants = romaji_to_hiragana_variants(word)
    return variants[0] if variants else None


def connect():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS dictionaries (id INTEGER PRIMARY KEY, path TEXT UNIQUE, title TEXT, stamp TEXT, count INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS entries (dictionary_id INTEGER, term TEXT, reading TEXT, glossary TEXT)')
    columns = {row[1] for row in db.execute('PRAGMA table_info(dictionaries)')}
    if 'enabled' not in columns:
        db.execute('ALTER TABLE dictionaries ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1')
    if 'sort_order' not in columns:
        db.execute('ALTER TABLE dictionaries ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0')
        db.execute('UPDATE dictionaries SET sort_order=id')
    db.execute('CREATE TABLE IF NOT EXISTS term_metadata (dictionary_id INTEGER,term TEXT,mode TEXT,data TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS term_metadata_lookup ON term_metadata(term,dictionary_id,mode)')
    for column in ('has_frequency','has_pitch'):
        if column not in columns:db.execute(f'ALTER TABLE dictionaries ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0')
    for column in ('has_kanji','has_kanji_frequency'):
        if column not in columns:db.execute(f'ALTER TABLE dictionaries ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0')
    db.execute('CREATE TABLE IF NOT EXISTS kanji_entries (dictionary_id INTEGER,character TEXT,onyomi TEXT,kunyomi TEXT,tags TEXT,meanings TEXT,stats TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS kanji_entries_lookup ON kanji_entries(character,dictionary_id)')
    db.execute('CREATE TABLE IF NOT EXISTS kanji_metadata (dictionary_id INTEGER,character TEXT,mode TEXT,data TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS kanji_metadata_lookup ON kanji_metadata(character,dictionary_id,mode)')
    db.execute('CREATE TABLE IF NOT EXISTS dictionary_tags (dictionary_id INTEGER,name TEXT,notes TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS dictionary_tags_lookup ON dictionary_tags(dictionary_id,name)')
    db.execute("UPDATE dictionaries SET has_pitch=1 WHERE lower(title) LIKE '%nhk%' AND has_pitch=0")
    db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    if db.execute('SELECT 1 FROM dictionaries LIMIT 1').fetchone():
        db.execute("INSERT OR IGNORE INTO settings VALUES('initialized','1')")
    db.execute('CREATE INDEX IF NOT EXISTS entries_term ON entries(term)')
    db.execute('CREATE INDEX IF NOT EXISTS entries_reading ON entries(reading)')
    db.execute('CREATE INDEX IF NOT EXISTS entries_dictionary ON entries(dictionary_id)')
    db.commit()
    return db


def archive_info(path):
    with zipfile.ZipFile(path) as z:
        index = json.loads(z.read('index.json'))
        if not any(re.fullmatch(r'(?:term|kanji)_(?:meta_)?bank_\d+\.json', n) for n in z.namelist()):
            return None
        return index.get('title', path.stem)


class Importer(QObject):
    progress = Signal(str)
    finished = Signal(str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        db = connect()
        imported, skipped, errors = 0, 0, []
        for path in self.paths:
            try:
                stamp = f'{path.stat().st_mtime_ns}:{path.stat().st_size}:metadata-1:kanji-1'
                old = db.execute('SELECT id,stamp FROM dictionaries WHERE path=?', (str(path),)).fetchone()
                if old and old[1] == stamp:
                    skipped += 1
                    continue
                title = archive_info(path)
                if title is None:
                    errors.append(f'{path.name}: no term, character, frequency or pitch data found')
                    continue
                self.progress.emit(f'Indexing {title}… ({imported + skipped + 1}/{len(self.paths)})')
                with zipfile.ZipFile(path) as z:
                    names = sorted((n for n in z.namelist() if re.fullmatch(r'term_bank_\d+\.json', n)), key=lambda n: int(n[10:-5]))
                    db.execute('BEGIN')
                    if old:
                        did = old[0]
                        db.execute('DELETE FROM entries WHERE dictionary_id=?', (did,))
                        db.execute('DELETE FROM term_metadata WHERE dictionary_id=?', (did,))
                        for table in ('kanji_entries','kanji_metadata','dictionary_tags'):
                            db.execute('DELETE FROM '+table+' WHERE dictionary_id=?', (did,))
                    else:
                        next_order = db.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM dictionaries').fetchone()[0]
                        did = db.execute('INSERT INTO dictionaries(path,title,stamp,count,sort_order) VALUES(?,?,?,0,?)', (str(path), title, stamp, next_order)).lastrowid
                    count = 0
                    has_frequency=has_pitch=False
                    has_kanji=has_kanji_frequency=False
                    # Older character dictionaries were distributed as term banks.
                    legacy_kanji = bool({'kanji','hanzi'} & {part.lower() for part in path.parts[:-1]}) or bool(re.match(r'\[(?:Kanji|Hanzi)[^\]]*\]',path.name,re.I))
                    for name in names:
                        rows = json.loads(z.read(name))
                        batch = [(did, str(row[0]), str(row[1]), json.dumps(row[5], ensure_ascii=False))
                                 for row in rows if isinstance(row, list) and len(row) > 5 and isinstance(row[0], str)]
                        if legacy_kanji:
                            batch=[(did,term,'',reading,'',glossary,'{}') for did,term,reading,glossary in batch if len(term)==1]
                            db.executemany('INSERT INTO kanji_entries VALUES(?,?,?,?,?,?,?)',batch)
                        else:
                            db.executemany('INSERT INTO entries VALUES(?,?,?,?)', batch)
                        count += len(batch)
                        if not legacy_kanji:has_pitch |= any('pitchAccentText' in row[3] for row in batch)
                    for name in sorted(n for n in z.namelist() if re.fullmatch(r'term_meta_bank_\d+\.json',n)):
                        rows=json.loads(z.read(name))
                        batch=[(did,row[0],row[1],json.dumps(row[2],ensure_ascii=False)) for row in rows if isinstance(row,list) and len(row)>=3 and isinstance(row[0],str) and row[1] in ('freq','pitch')]
                        db.executemany('INSERT INTO term_metadata VALUES (?,?,?,?)',batch)
                        has_frequency |= any(row[2]=='freq' for row in batch)
                        has_pitch |= any(row[2]=='pitch' for row in batch)
                        count+=len(batch)
                    for name in sorted(n for n in z.namelist() if re.fullmatch(r'kanji_bank_\d+\.json',n)):
                        rows=json.loads(z.read(name))
                        batch=[(did,row[0],str(row[1]),str(row[2]),str(row[3]),json.dumps(row[4],ensure_ascii=False),json.dumps(row[5],ensure_ascii=False)) for row in rows if isinstance(row,list) and len(row)>=6 and isinstance(row[0],str)]
                        db.executemany('INSERT INTO kanji_entries VALUES (?,?,?,?,?,?,?)',batch)
                        has_kanji |= bool(batch);count+=len(batch)
                    for name in sorted(n for n in z.namelist() if re.fullmatch(r'kanji_meta_bank_\d+\.json',n)):
                        rows=json.loads(z.read(name))
                        batch=[(did,row[0],row[1],json.dumps(row[2],ensure_ascii=False)) for row in rows if isinstance(row,list) and len(row)>=3 and isinstance(row[0],str) and row[1]=='freq']
                        db.executemany('INSERT INTO kanji_metadata VALUES (?,?,?,?)',batch)
                        has_kanji_frequency |= bool(batch);count+=len(batch)
                    for name in sorted(n for n in z.namelist() if re.fullmatch(r'tag_bank_\d+\.json',n)):
                        rows=json.loads(z.read(name))
                        db.executemany('INSERT INTO dictionary_tags VALUES (?,?,?)',[(did,str(row[0]),str(row[3])) for row in rows if isinstance(row,list) and len(row)>=4])
                    has_kanji |= legacy_kanji and bool(names)
                    db.execute('UPDATE dictionaries SET title=?,stamp=?,count=?,has_frequency=?,has_pitch=?,has_kanji=?,has_kanji_frequency=? WHERE id=?', (title,stamp,count,int(has_frequency),int(has_pitch),int(has_kanji),int(has_kanji_frequency),did))
                    db.commit()
                imported += 1
            except Exception as e:
                db.rollback()
                errors.append(f'{path.name}: {e}')
        db.close()
        result = f'Ready — {imported} imported, {skipped} already indexed.'
        if errors:
            result += ' Errors: ' + '; '.join(errors[:3])
        self.finished.emit(result)


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


def search_patterns(query):
    """Literal prefix by default; explicit * and ? use whole-word glob matching.

    Backslash quotes the next character. Square brackets are always literal.
    Romaji conversion applies to each literal part around wildcards.
    """
    parts, literal, wildcard = [], '', False
    def flush():
        nonlocal literal
        if literal:
            variants = romaji_to_hiragana_variants(literal) or (literal,)
            parts.append([(v, False) for v in variants])
            literal = ''
    i = 0
    while i < len(query):
        char = query[i]
        if char == '\\' and i + 1 < len(query):
            i += 1
            literal += query[i]
        elif char in '*?':
            flush()
            parts.append([(char, True)])
            wildcard = True
        else:
            literal += char
        i += 1
    flush()
    combinations = list(islice(product(*parts), 32))
    def escape(value):
        return ''.join({'[': '[[]', '*': '[*]', '?': '[?]'}.get(c, c) for c in value)
    patterns = tuple(dict.fromkeys(''.join(value if special else escape(value)
        for value, special in combo) + ('' if wildcard else '*') for combo in combinations))
    exact = tuple(''.join(value for value, special in combo) for combo in combinations) if not wildcard else (query,)
    return exact, patterns


def search_entries(db, query):
    """Indexed candidate lookup; rank metadata before loading large definitions."""
    query = query.strip()
    if not query:
        return []
    variants, patterns = search_patterns(query)
    slots = ','.join('?' for _ in variants)
    rank = f'CASE WHEN e.term IN ({slots}) THEN 0 WHEN e.reading IN ({slots}) THEN 1 ELSE 2 END'
    candidates = ' UNION '.join(f'SELECT rowid FROM entries WHERE {column} GLOB ?'
        for column in ('term', 'reading') for _ in patterns)
    return db.execute(f"""WITH candidates AS ({candidates}), ranked AS (
        SELECT e.rowid AS entry_id,e.term,e.reading,d.id,d.title,d.sort_order,
          {rank} AS match_rank,
          row_number() OVER (PARTITION BY d.id ORDER BY
            {rank},length(e.term),e.term,e.reading,e.rowid) AS entry_number
        FROM candidates c JOIN entries e ON e.rowid=c.rowid
        JOIN dictionaries d ON d.id=e.dictionary_id WHERE d.enabled=1)
        SELECT r.term,r.reading,e.glossary,r.id,r.title FROM ranked r
        JOIN entries e ON e.rowid=r.entry_id WHERE r.entry_number<=40
        ORDER BY r.sort_order,r.id,r.match_rank,length(r.term),r.term,r.reading,r.entry_id""",
        (*patterns, *patterns, *variants, *variants, *variants, *variants)).fetchall()


class ResultTree(QTreeWidget):
    def __init__(self):
        super().__init__()
        self.was_current_on_press = False

    def mousePressEvent(self, event):
        self.was_current_on_press = self.itemAt(event.position().toPoint()) is self.currentItem()
        super().mousePressEvent(event)


class DictionaryRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(180,62)

    def paint(self,painter,option,index):
        opt=QStyleOptionViewItem(option);self.initStyleOption(opt,index)
        title,count,kind=index.data(Qt.ItemDataRole.UserRole+1) or (index.data(),0,'Definitions')
        opt.text=''
        style=option.widget.style() if option.widget else QApplication.style()
        painter.save()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem,opt,painter,option.widget)
        rect=style.subElementRect(QStyle.SubElement.SE_ItemViewItemText,opt,option.widget).adjusted(8,0,-10,0)
        painter.setClipRect(option.rect)
        font=QFont(option.font);font.setPointSize(11);font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font);painter.setPen(QColor('#e5ecef'))
        painter.drawText(rect.adjusted(0,8,0,-29),Qt.AlignmentFlag.AlignVCenter,QFontMetrics(font).elidedText(str(title),Qt.TextElideMode.ElideRight,rect.width()))
        font.setPointSize(9);font.setWeight(QFont.Weight.Normal);painter.setFont(font);painter.setPen(QColor('#a4b3bd'))
        painter.drawText(rect.adjusted(0,31,0,-7),Qt.AlignmentFlag.AlignVCenter,f'{kind} · {count:,} '+('record' if count==1 else 'records'))
        painter.restore()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = connect()
        self.folder_config = APP_DIR / 'dictionary-folder.json'
        try:
            self.dictionary_folder = Path(json.loads(self.folder_config.read_text())['folder'])
        except (OSError, ValueError, KeyError):
            self.dictionary_folder = COLLECTION
        self.setWindowTitle('Ukijiten')
        self.resize(1100, 760)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Type a Japanese word, reading, or romaji…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.schedule_search)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.lookup)
        self.results = ResultTree()
        self.results.setHeaderHidden(True)
        self.results.setRootIsDecorated(True)
        self.results.setExpandsOnDoubleClick(False)
        self.results.setUniformRowHeights(True)
        self.results.currentItemChanged.connect(self.show_selection)
        self.results.itemClicked.connect(self.result_clicked)
        self.results.itemDoubleClicked.connect(self.result_double_clicked)
        self.page = QTextBrowser()
        self.page.setOpenExternalLinks(False)
        self.page.setOpenLinks(False)
        self.page.anchorClicked.connect(self.follow_link)
        self.page.setStyleSheet('font-size: 17px;')
        self.entries = []
        self.import_thread = None
        splitter = QSplitter()
        splitter.addWidget(self.results)
        splitter.addWidget(self.page)
        splitter.setStretchFactor(1, 3)
        top = QHBoxLayout()
        top.addWidget(self.search)
        add_zip = QPushButton('Add ZIP(s)…')
        add_zip.clicked.connect(self.add_zips)
        top.addWidget(add_zip)
        lookup_layout = QVBoxLayout()
        lookup_layout.addLayout(top)
        lookup_layout.addWidget(splitter)
        lookup_tab = QWidget()
        lookup_tab.setLayout(lookup_layout)

        self.dictionary_list = QListWidget()
        self.dictionary_list.setItemDelegate(DictionaryRowDelegate(self.dictionary_list))
        self.dictionary_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.dictionary_list.setMouseTracking(True)
        self.dictionary_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.dictionary_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.dictionary_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.dictionary_list.itemChanged.connect(self.dictionary_toggled)
        self.dictionary_list.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self.save_dictionary_order))
        manage_layout = QVBoxLayout();manage_layout.setSpacing(12)
        manage_layout.setContentsMargins(0,0,0,0)
        toolbar=QHBoxLayout();toolbar.setSpacing(8)
        add=QPushButton('Add dictionaries…');add.clicked.connect(self.add_zips);toolbar.addWidget(add);toolbar.addStretch()
        self.add_dictionary_button=add
        self.select_all_button=QPushButton('Select all')
        self.select_all_button.clicked.connect(lambda:self.set_dictionaries_enabled(True))
        toolbar.addWidget(self.select_all_button)
        self.unselect_all_button=QPushButton('Unselect all')
        self.unselect_all_button.clicked.connect(lambda:self.set_dictionaries_enabled(False))
        toolbar.addWidget(self.unselect_all_button)
        manage_layout.addLayout(toolbar)
        hint=QLabel('Drag to reorder.');hint.setObjectName('dictionaryHint');manage_layout.addWidget(hint)
        manage_layout.addWidget(self.dictionary_list)
        footer=QHBoxLayout();footer.setSpacing(10)
        self.dictionary_status=QLabel();self.dictionary_status.setWordWrap(True);self.dictionary_status.setObjectName('dictionaryStatus')
        self.statusBar().messageChanged.connect(self.dictionary_status.setText)
        footer.addWidget(self.dictionary_status,1)
        remove_button=QPushButton('Remove dictionary');remove_button.clicked.connect(self.remove_dictionary)
        footer.addWidget(remove_button);manage_layout.addLayout(footer)
        def update_selection_actions():
            remove_button.setEnabled(bool(self.dictionary_list.selectedItems()))
        self.dictionary_list.itemSelectionChanged.connect(update_selection_actions)
        update_selection_actions()
        manage_tab = QWidget()
        manage_tab.setLayout(manage_layout)
        self.tabs = QTabWidget()
        self.tabs.addTab(lookup_tab, 'Lookup')
        self.tabs.addTab(manage_tab, 'Dictionaries')
        self.setCentralWidget(self.tabs)
        self.refresh_dictionaries()
        self.statusBar().showMessage('Ready')
        focus = QAction('Focus search', self)
        focus.setShortcut(QKeySequence('Ctrl+L'))
        focus.triggered.connect(self.search.setFocus)
        self.addAction(focus)
        self.search.setFocus()
        if not self.db.execute("SELECT 1 FROM settings WHERE key='initialized'").fetchone():
            self.db.execute("INSERT INTO settings VALUES('initialized','1')")
            self.db.commit()
            candidates = list(COLLECTION.rglob('*JMdict (Recommended).zip')) if COLLECTION.exists() else []
            if candidates:
                self.import_paths(candidates)
            else:
                self.page.setHtml('<h2>Add Yomitan ZIP dictionaries</h2><p>Use Add ZIP(s) to select one or more dictionaries.</p>')

    def refresh_dictionaries(self):
        self.dictionary_list.blockSignals(True)
        self.dictionary_list.clear()
        rows = self.db.execute('SELECT id,title,path,count,enabled,has_frequency,has_pitch,has_kanji,has_kanji_frequency FROM dictionaries ORDER BY sort_order,id').fetchall()
        for did,title,path,count,enabled,frequency,pitch,kanji,kanji_frequency in rows:
            item=QListWidgetItem(title)
            kinds=[label for label,exists in [('Frequency',frequency),('Pitch accent',pitch),('Kanji / Hanzi',kanji),('Kanji frequency',kanji_frequency)] if exists]
            kind=' + '.join(kinds) if kinds else 'Definitions'
            item.setData(Qt.ItemDataRole.UserRole+1,(title,count,kind))
            item.setData(Qt.ItemDataRole.UserRole, did)
            item.setToolTip(path or '')
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            self.dictionary_list.addItem(item)
        self.dictionary_list.blockSignals(False)
        self.tabs.setTabText(1, f'Dictionaries ({len(rows)})')

    def open_dictionary_folder(self):
        if not self.dictionary_folder.is_dir():
            QMessageBox.information(self, 'Dictionary folder', 'Choose a dictionary folder first.')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.dictionary_folder)))

    def set_dictionaries_enabled(self, enabled):
        items = [self.dictionary_list.item(i) for i in range(self.dictionary_list.count())]
        self.db.executemany('UPDATE dictionaries SET enabled=? WHERE id=?',
            [(int(enabled), item.data(Qt.ItemDataRole.UserRole)) for item in items])
        self.db.commit()
        self.dictionary_list.blockSignals(True)
        for item in items:
            item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.dictionary_list.blockSignals(False)
        self.lookup()

    def dictionary_toggled(self, item):
        did = item.data(Qt.ItemDataRole.UserRole)
        self.db.execute('UPDATE dictionaries SET enabled=? WHERE id=?',
                        (int(item.checkState() == Qt.CheckState.Checked), did))
        self.db.commit()
        self.lookup()

    def save_dictionary_order(self):
        ids = [self.dictionary_list.item(i).data(Qt.ItemDataRole.UserRole)
               for i in range(self.dictionary_list.count())]
        self.db.executemany('UPDATE dictionaries SET sort_order=? WHERE id=?',
                            [(i + 1, did) for i, did in enumerate(ids)])
        self.db.commit()
        self.lookup()

    def remove_dictionary(self):
        items=self.dictionary_list.selectedItems()
        if not items:return
        if self.import_thread is not None and self.import_thread.isRunning():
            self.statusBar().showMessage('Wait for importing to finish.');return
        ids=[item.data(Qt.ItemDataRole.UserRole) for item in items]
        message='Remove '+(items[0].text() if len(items)==1 else str(len(items))+' selected dictionaries')+'?\n\nThe ZIP files will be kept.'
        if QMessageBox.question(self.dictionary_list.window(),'Remove dictionaries',message,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        with self.db:
            for did in ids:
                self.db.execute('DELETE FROM entries WHERE dictionary_id=?',(did,))
                self.db.execute('DELETE FROM term_metadata WHERE dictionary_id=?',(did,))
                for table in ('kanji_entries','kanji_metadata','dictionary_tags'):
                    self.db.execute('DELETE FROM '+table+' WHERE dictionary_id=?',(did,))
                self.db.execute('DELETE FROM dictionaries WHERE id=?',(did,))
        self.refresh_dictionaries();self.lookup()
        self.statusBar().showMessage(f'Removed {len(ids)} dictionaries. ZIP files kept.')

    def add_zips(self):
        paths, _ = QFileDialog.getOpenFileNames(self.dictionary_list.window(), 'Choose Yomitan dictionaries', str(self.dictionary_folder), 'ZIP archives (*.zip)')
        self.import_paths([Path(p) for p in paths])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose dictionary folder', str(self.dictionary_folder))
        if folder:
            self.dictionary_folder = Path(folder)
            self.folder_config.parent.mkdir(parents=True, exist_ok=True)
            self.folder_config.write_text(json.dumps({'folder': folder}))
            self.import_paths(sorted(Path(folder).rglob('*.zip')))

    def import_paths(self, paths):
        if not paths:
            return
        if self.import_thread is not None and self.import_thread.isRunning():
            self.statusBar().showMessage('Please wait for the current import to finish.')
            return
        self.import_thread = QThread(self)
        self.add_dictionary_button.setEnabled(False)
        self.statusBar().showMessage('Importing dictionaries…')
        self.worker = Importer(paths)
        self.worker.moveToThread(self.import_thread)
        self.import_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.finished.connect(self.import_done)
        self.worker.finished.connect(self.import_thread.quit)
        self.import_thread.finished.connect(self.worker.deleteLater)
        self.import_thread.finished.connect(self.import_thread.deleteLater)
        self.import_thread.finished.connect(lambda: setattr(self, 'import_thread', None))
        self.import_thread.start()

    def import_done(self, message):
        self.add_dictionary_button.setEnabled(True)
        self.statusBar().showMessage(message)
        self.refresh_dictionaries()
        self.lookup()

    def schedule_search(self):
        self.timer.start()

    def lookup(self):
        self.timer.stop()
        query = self.search.text().strip()
        self.results.clear()
        self.entries = []
        if not query:
            self.page.clear()
            return
        self.entries = search_entries(self.db, query)
        if not self.entries:
            self.page.setHtml('<p>No matches. Try the dictionary form or add more ZIPs.</p>')
            return
        sections = []
        current_group = None
        first_item = None
        for number, (term, reading, glossary, did, title) in enumerate(self.entries):
            if did != current_group:
                current_group = did
                parent = QTreeWidgetItem([title])
                parent.setData(0, Qt.ItemDataRole.UserRole, f'entry-{number}')
                self.results.addTopLevelItem(parent)
                parent.setExpanded(False)
                sections.append(f'<section class="dictionary"><h2>{html.escape(title)}</h2>')
                if first_item is None:
                    first_item = parent
            label = f'{term}  {reading}' if reading else term
            child = QTreeWidgetItem(parent, [label])
            child.setData(0, Qt.ItemDataRole.UserRole, f'entry-{number}')
            sections.append(f'<article><a name="entry-{number}"></a><h3>{html.escape(term)}</h3>')
            if reading:
                sections.append(f'<div class="reading">{html.escape(reading)}</div>')
            sections.append(f'<div class="definition">{render(json.loads(glossary))}</div></article>')
            if number + 1 == len(self.entries) or self.entries[number + 1][3] != did:
                sections.append('</section>')
        self.page.setHtml('''<html><head><style>
            body{font-family:sans-serif;font-size:17px;line-height:1.55;padding:14px;color:#ddd;background:#202124}
            h2{font-size:21px;color:#8ab4f8;margin:0 0 14px} h3{font-size:28px;margin:0 0 3px}
            .reading{color:#aaa;margin-bottom:18px} .dictionary{margin-bottom:30px}
            article{border-bottom:1px solid #555;padding:0 0 26px;margin:0 0 26px}
            a{color:#8ab4f8} li{margin:5px 0} .media{color:#aaa;font-style:italic}
            table{border-collapse:collapse} td,th{border:1px solid #666;padding:5px}
            </style></head><body>''' + ''.join(sections) + '</body></html>')
        self.results.setCurrentItem(first_item)
        self.page.verticalScrollBar().setValue(0)

    def show_selection(self, item, _previous=None):
        if item is not None:
            self.page.scrollToAnchor(item.data(0, Qt.ItemDataRole.UserRole))

    def result_clicked(self, item, _column):
        if item.parent() is None and self.results.was_current_on_press:
            item.setExpanded(not item.isExpanded())
        self.show_selection(item)

    def result_double_clicked(self, item, _column):
        if item.parent() is None:
            item.setExpanded(True)
        self.show_selection(item)

    def follow_link(self, url):
        if url.fragment():
            self.page.scrollToAnchor(url.fragment())
        elif url.query():
            word = parse_qs(url.query()).get('query', [''])[0]
            if word:
                self.search.setText(word)

    def closeEvent(self, event):
        if self.import_thread is not None and self.import_thread.isRunning():
            QMessageBox.information(self, 'Indexing', 'Please wait until dictionary indexing finishes.')
            event.ignore()
            return
        self.db.close()
        super().closeEvent(event)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    app = QApplication(sys.argv)
    query = ''
    if '--popup' in argv:
        query, accepted = QInputDialog.getText(None, 'Japanese Lookup', 'Enter word:')
        if not accepted or not query.strip():
            return 0
    window = Window()
    if query:
        window.search.setText(query.strip())
        window.lookup()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
