"""Version guard and host value inputs for the Taiko Domain client."""
from importlib.metadata import version

CORE_VERSION = '0.1.2'
CONTRACT_VERSION = '0.1.0'

def assert_domain_versions():
    for package, expected in (('sakura-taiko-core', CORE_VERSION), ('sakura-taiko-contract', CONTRACT_VERSION)):
        actual = version(package)
        if actual != expected:
            raise RuntimeError(f'{package} version mismatch: expected {expected}, got {actual}')

def identity_inputs():
    from plugins.utils.duplicate_versions import _group_cache
    _, by_id, by_title = _group_cache()
    return {sid: group.default_id for sid, group in by_id.items()}, by_id, by_title

def visibility_inputs(records=(), songs=None):
    from plugins.utils.song_visibility import load_song_index
    from sakura_taiko_core.chart.visibility import is_song_id_publicly_visible
    index = load_song_index()
    ids = set(index)
    for record in records:
        try: ids.add(int(record.get('song_no')))
        except (TypeError, ValueError): pass
    for row in (songs or {}).values():
        try: ids.add(int(row.get('id')))
        except (TypeError, ValueError): pass
    return {sid for sid in ids if is_song_id_publicly_visible(sid, song_index=index)}

assert_domain_versions()
