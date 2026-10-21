"""One costume compositor for center, client and offline personal displays.

The resource catalog is extracted from the official mini program. Paths refer
only to local assets; rendering never fetches a URL or reads player state.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


def _integer(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@lru_cache(maxsize=4)
def _read_catalog(path, revision):
    with path.open(encoding='utf-8') as source:
        catalog = json.load(source)
    if catalog.get('schemaVersion') != 1:
        raise ValueError('Unsupported costume catalog version')
    for name in ('cosIconList', 'headIconList', 'bodyIconList', 'paintIconList', 'accessoriesIconList'):
        catalog[name] = {entry['id']: entry for entry in catalog[name]}
    return catalog


def load_catalog(root):
    path = Path(root) / 'catalog.json'
    stat = path.stat()
    return _read_catalog(path, (stat.st_mtime_ns, stat.st_size))


def _indexed(entries, index):
    return entries[index].get('url', '') if 0 <= index < len(entries) else ''


@dataclass(frozen=True)
class Layer:
    path: str
    z: int


def plan_layers(costume, catalog):
    """Use official z indices and stable DOM order for layers with equal z."""
    def entry(name, field):
        return catalog[name].get(_integer(costume.get(field)), {})

    cos = entry('cosIconList', 'costume_1')
    head = entry('headIconList', 'costume_2')
    body = entry('bodyIconList', 'costume_3')
    paint = entry('paintIconList', 'costume_4')
    accessory = entry('accessoriesIconList', 'costume_5') if costume.get('costume_5') not in (None, '') else {}
    cs, hs, bs = (item.get('special', {}) for item in (cos, head, body))
    face = _integer(costume.get('color_face'))
    torso = _integer(costume.get('color_body'), 1)
    skin = _integer(costume.get('color_limb'), 3)
    z_body = bs.get('specialBodyZIndex', cs.get('specialBodyZIndex', 0))
    z_part = z_body + 1 if z_body else 3

    def priority(key, default):
        return next((rules[key] for rules in (hs, bs, cs) if key in rules), default)

    def base(name, index):
        # A special suit may intentionally omit one of the default base layers.
        return _indexed(cs.get(name, []) if cs else catalog[name], index)

    def special(rules, name, index):
        return _indexed(rules.get(name, []), index)

    line = next((rules['line'] for rules in (cs, hs, bs) if rules.get('line')), catalog['defaultLine'])
    adapted_paints = catalog.get('specialHeadPaintListMap', {}).get(str(head.get('id')))
    paint_url = _indexed(adapted_paints, _integer(costume.get('costume_4'))) if adapted_paints else paint.get('url', '')
    if any(rules.get('lineHasFace') for rules in (cs, hs, bs)):
        paint_url = ''
    cos_url = cos.get('url', '')
    if cos.get('levelList'):
        level = _integer(costume.get('got_dan_max'))
        cos_url = next((row['url'] for row in cos['levelList'] if row['id'] == level), cos_url)

    layers = [
        Layer(base('bodyColorList', torso), 1),
        Layer(special(bs, 'specialBodyToBodyColorList', torso), z_body or 2),
        Layer(base('skinColorList', skin), 1),
        Layer(special(bs, 'specialBodyToSkinColorList', skin), z_body - 1 if z_body else 2),
        Layer(base('headColorList', face), z_part),
        Layer(line, priority('lineZIndex', 2)),
        Layer(special(bs, 'specialBodyToHeadColorList', face), z_part),
        Layer(body.get('url', ''), z_part),
        Layer(special(hs, 'specialHeadToSkinColorList', skin), z_part),
        Layer(special(hs, 'specialHeadToHeadColorList', face), hs.get('specialHeadToHeadColorZIndex', z_part)),
        Layer(paint_url, priority('specialPaintZIndex', z_part)),
        Layer(special(hs, 'specialHeadToBodyColorList', torso), z_part),
        Layer(head.get('url', ''), z_part),
        Layer(cos_url, 3),
        Layer(accessory.get('url', ''), 6),
    ]
    return sorted((layer for layer in layers if layer.path), key=lambda layer: layer.z)


def render_dress(userdata, assets_dir):
    root = Path(assets_dir).resolve()
    catalog = load_catalog(root)
    costume = (userdata.get('profile') or {}).get('gameCostume') or {}
    layers = plan_layers(costume, catalog)
    canvas = None
    for layer in layers:
        path = (root / layer.path).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Costume asset path escapes its root')
        try:
            with Image.open(path) as source:
                image = source.convert('RGBA')
        except FileNotFoundError:
            logger.warning('Missing costume asset: %s', layer.path)
            continue
        if canvas is None:
            canvas = Image.new('RGBA', image.size)
        if image.size != canvas.size:
            # CSS renders all layers at the same size; normalize identically.
            image = image.resize(canvas.size, Image.Resampling.LANCZOS)
        canvas.alpha_composite(image)
    if canvas is None:
        raise FileNotFoundError('No costume layers available')
    return canvas
