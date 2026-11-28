"""Qt-independent query normalization and ranked dictionary search."""
from itertools import islice, product
import re

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


