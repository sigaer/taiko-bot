"""Small installed-wheel cache regression, also runnable in packaging CI."""
import json
import os
from pathlib import Path
import tempfile
from importlib.metadata import version

with tempfile.TemporaryDirectory(prefix='catalog-revision-',dir=os.environ.get('QA_RUN_TMPDIR',os.environ.get('RUNNER_TEMP','/var/tmp'))) as directory:
    root=Path(directory);(root/'songs').mkdir()
    os.environ.update(TAIKO_BOT_ROOT=str(root),TAIKO_CENTER_ROOT=str(root),TAIKO_RUNTIME_ENV_FILE=str(root/'absent.env'))
    path=root/'songs/song_data.json'
    rows=[{'id':10001,'song_name':'A','song_name_jp':'A','level_4':9}, {'id':10002,'song_name':'B','song_name_jp':'B','level_4':9}]
    path.write_text(json.dumps(rows))
    from taiko_bot.runtime.player.center.duplicate_versions import _group_cache
    if version('sakura-taiko-core')=='0.1.2':
        from taiko_bot.runtime.player.client.recommendation_support import catalog
    else:
        catalog=None
    before=_group_cache(path)[1];assert before[10001].default_id!=before[10002].default_id
    if catalog:assert catalog.load_song_index()[10002]['song_name']=='B'
    stamp=path.stat().st_mtime_ns
    rows[1].update(song_name='A',song_name_jp='A');path.write_text(json.dumps(rows));os.utime(path,ns=(stamp+1_000_000,stamp+1_000_000))
    after=_group_cache(path)[1];assert after[10001].default_id==after[10002].default_id
    if catalog:assert catalog.load_song_index()[10002]['song_name']=='A'
    # Returning to the previous catalog must create a fresh observation as well.
    rows[1].update(song_name='B',song_name_jp='B');path.write_text(json.dumps(rows));os.utime(path,ns=(stamp+2_000_000,stamp+2_000_000))
    assert _group_cache(path)[1][10001].default_id!=_group_cache(path)[1][10002].default_id
    if catalog:assert catalog.load_song_index()[10002]['song_name']=='B'
    print('Installed identity cache refresh/switch-back'+(' + client visibility' if catalog else '')+': PASS')
