"""Data-sensitive fixture image, not the production tinfo layout."""
from hashlib import sha256
from io import BytesIO
from PIL import Image, ImageDraw


def render(current, song_no, failure=None):
    if failure == 'missing':
        raise FileNotFoundError('userdata not found')
    if failure == 'error':
        raise RuntimeError('fixture renderer error')
    if failure == 'type':
        raise TypeError('fixture bad score')
    if failure == 'jpeg':
        return b'invalid image'
    song = next((s for s in current['songs'] if s['song_no'] == song_no), None)
    if song is None:
        raise LookupError('fixture song record absent')
    color = tuple(sha256(current['profile']['mydon_name'].encode()).digest()[:3])
    with Image.new('RGB', (160, 96), color) as im:
        draw = ImageDraw.Draw(im)
        width = max(1, min(158, int(song['high_score']) * 158 // 1000000))
        draw.rectangle((1, 30, width, 60), fill=(255,255,255))
        draw.rectangle((1, 65, min(158, song['stage_cnt']*10), 80), fill=(30,30,30))
        out = BytesIO()
        im.save(out, format='PNG')
        return out.getvalue()


def jpeg(data, quality=85):
    with Image.open(BytesIO(data)) as source:
        with source.convert('RGB') as image:
            out = BytesIO()
            image.save(out, format='JPEG', quality=quality, optimize=True)
            return out.getvalue()


def query(name):
    return {'none': [], 'many': [[7,'Neon'],[8,'Echo']], 'fuzzy': [[7,'Neon',50]],
            'accepted': [[7,'Neon',90]], 'invalid-id': [[-1,'Invalid']],
            'absent-record': [[9,'Other']], 'query-error': None}.get(name, [[7,'Neon']])


def rejected(rows):
    return bool(rows) and len(rows)==1 and len(rows[0])>=3 and isinstance(rows[0][2],(int,float)) and float(rows[0][2])/100 < 0.7


def hint(rows):
    return f'你要找的可能是：{rows[0][1]}\n匹配度：{float(rows[0][2])/100:.2f}'
