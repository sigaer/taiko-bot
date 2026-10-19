"""Version-aware title matching for the public arcade song list."""
import re
import unicodedata
from html.parser import HTMLParser


def normalize_title(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    value = value.translate(str.maketrans({'‐': '-', '‑': '-', '–': '-', '—': '-', '−': '-', '’': "'", '‘': "'", '〜': '~'}))
    # Symbols such as ♡ and ! distinguish recordings; never discard them.
    return ''.join(char for char in value if not char.isspace())


class SongTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = self.cell = None
        self.paragraph_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th') and self.row is not None:
            self.cell = {'tag': tag, 'title': [], 'subtitle': [], 'all': []}
        if tag == 'p':
            self.paragraph_depth += 1

    def handle_data(self, value):
        if self.cell is not None:
            self.cell['all'].append(value)
            self.cell['subtitle' if self.paragraph_depth else 'title'].append(value)

    def handle_endtag(self, tag):
        if tag == 'p':
            self.paragraph_depth = max(0, self.paragraph_depth - 1)
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append({key: ' '.join(' '.join(value).split()) if isinstance(value, list) else value
                             for key, value in self.cell.items()})
            self.cell = None
        if tag == 'tr' and self.row is not None:
            if len(self.row) >= 7 and self.row[0]['tag'] == 'th':
                title = re.sub(r'(?:\s+(?:NEW!|MEDAL(?:\(おに裏\))?|AI BATTLE|CAMPAIGN|CODE|SECRET))+$', '', self.row[0]['title']).strip()
                levels = [cell['all'] for cell in self.row[2:7]]
                if title and all(re.fullmatch(r'\d+|-', level) for level in levels):
                    self.rows.append({'title': title, 'subtitle': self.row[0]['subtitle']})
            self.row = None


# Public title spelling/localization differences, reviewed against artist and
# chart metadata on 2026-10-19. IDs are only accepted when in the current CN
# response; rules never add songs to the national roster.
TITLE_IDS = {'晩餐歌': 1358, 'Miss You 3000': 1331, 'Doppelgängers': 1133,
             'アリア': 1431, 'ALiVE': 930, 'Synchronicity': 523, 'Emma': 1032}
VERSION_IDS = {}
for slug in ('anime', 'game'):
    VERSION_IDS[(slug, 'エンジェル ドリーム', '「アイドルマスター シンデレラガールズ」より')] = 153
for title, cover_id, cover_subtitle, original_id, original_subtitle in (
    ('いっそこのままで', 1263, '山神カルタ', 939, 'ミフメイ(BNSI) feat. 相沢'),
    ('濃紅', 1257, 'レヴィ・エリファ', 450, '黒沢ダイスケ × 小寺可南子'),
    ('ヘイラ', 1264, 'ましろ爻', 1146, 'necchi'),
    ('エンジェル ドリーム', 1265, 'フレン・E・ルスタリオ', 433, ''),
    ('CYBERgenicALICE', 1260, '先斗寧', 750, ''),
    ('Fly away', 1258, '伏見ガク', 141, ''),
    ('ボクハシンセ', 1266, '花畑チャイカ', 191, ''),
    ('マリオネットピュア', 1261, 'リゼ・ヘルエスタ', 527, ''),
    ('Phoenix', 1262, 'レオス・ヴィンセント', 323, ''),
    ('ファミレスウォーズ', 1259, '本間ひまわり', 137, ''),
):
    VERSION_IDS[('namco', title, cover_subtitle + ' / FOCUS ON (にじさんじ) × 太鼓の達人')] = cover_id
    VERSION_IDS[('namco', title, original_subtitle)] = original_id


def match_song(slug, official, by_title, by_id):
    title, subtitle = official['title'], official['subtitle']
    override = VERSION_IDS.get((slug, title, subtitle), TITLE_IDS.get(title))
    candidates = {override} if override is not None else by_title.get(normalize_title(title), set())
    candidates = {sid for sid in candidates if sid in by_id}
    if len(candidates) != 1:
        return None
    sid = next(iter(candidates))
    # A new overseas cover must not bind to the only locally available original.
    if ('FOCUS ON' in subtitle) != ('FOCUS ON' in str(by_id[sid].get('subtitle', ''))):
        return None
    return sid
