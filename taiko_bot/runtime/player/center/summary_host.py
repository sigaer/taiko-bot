"""Authorized summary Host: legacy cache persistence and public input preparation."""
from io import BytesIO
from hashlib import sha256
from dataclasses import asdict
import json
from PIL import Image
from taiko_application.private_input import thaw
from ...public.config import root
from . import summary_render

def render_summary(provider, private):
    provider.verify(private)
    path = root() / 'output' / f'{private.authorized_target.user_id}_taiko_2025_summary.png'
    virtual = len(private.authorized_target.members) > 1 or private.authorized_target.user_id.startswith('u0')
    stamp = path.with_suffix('.authorization.json')
    target = sha256(json.dumps(asdict(private.authorized_target),sort_keys=True).encode()).hexdigest()
    cache_valid = path.exists()
    cached = path.read_bytes() if cache_valid else b''
    if virtual and cache_valid:
        try:
            receipt = json.loads(stamp.read_text())
            cache_valid = receipt == {'target':target,'image':sha256(cached).hexdigest()}
        except (OSError,ValueError):
            cache_valid = False
    if cache_valid:
        with Image.open(BytesIO(cached)) as image:
            buf = BytesIO(); image.save(buf, format='png'); return buf.getvalue()
    if private.current_failure:
        raise ValueError('current unavailable')
    current = thaw(private.current)
    from .b30_support import score_calculator as calculator
    results = calculator.compute_all_from_userdata_records(current.get('songs') or [], json_path=root()/'songs/rating_structured_with_ids.json')
    image = summary_render.render_taiko_2025_summary(private.authorized_target.user_id,
        userdata=current, song_db=summary_render.load_song_db(),
        twso_rec=summary_render.find_twso_record(private.authorized_target.user_id),
        results=results, score_calc=calculator)
    provider.verify(private)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(image)
    if virtual:
        stamp.write_text(json.dumps({'target':target,'image':sha256(image).hexdigest()},sort_keys=True))
    return image
