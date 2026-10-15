"""Viewer adapters capture inputs without importing the retired host namespace."""
import hashlib
import json
import sys
import types
from pathlib import Path
import pytest
from taiko_bot.offline import viewer
from taiko_bot.offline._sha256_checkpoint import SHA256, NativeContinuation
from taiko_bot.offline.fingerprint import artifact_identity


def test_checkpoint_against_stdlib():
    for size in (0, 1, 55, 56, 63, 64, 65, 1000):
        prefix=bytes(range(256))*3
        checkpoint=SHA256().update(prefix).checkpoint()
        data=b'x'*size
        assert SHA256(checkpoint).update(data).hexdigest()==hashlib.sha256(prefix+data).hexdigest()
        assert NativeContinuation(checkpoint).update(data).hexdigest()==hashlib.sha256(prefix+data).hexdigest()


def test_artifact_content_and_location(tmp_path):
    a=tmp_path/'a.py';b=tmp_path/'b.py'
    a.write_text('same');b.write_text('same')
    before=artifact_identity({'module.py':a})
    assert artifact_identity({'module.py':b})==before
    b.write_text('else')
    assert artifact_identity({'module.py':b})!=before


def test_progress_preserves_call_and_output(monkeypatch, tmp_path):
    userdata={'profile':{'id':123},'songs':[]}
    (tmp_path/'123data.json').write_text(json.dumps(userdata))
    monkeypatch.setenv('TAIKO_USERDATA_DIR',str(tmp_path))
    from taiko_bot.runtime.player.center.progress_support import render
    calls=[]
    def real_input(user, *args, **kwargs):
        calls.append((user,args,kwargs));return b'PNG contract'
    for name,args in [('render_pass_progress_image_bytes',('10',)),('render_progress_image_bytes',('10',)),('render_star_progress_image_bytes',(9,)),('render_progress_image_bytes_by_list',('test',))]:
        monkeypatch.setattr(render,name,real_input)
        assert getattr(viewer,name)(123,*args,page=2)==b'PNG contract'
        assert calls[-1]==(123,args,dict(page=2,userdata=userdata))
    with pytest.raises(FileNotFoundError):viewer.render_star_progress_image_bytes(456,9)


def test_dani_options_keep_parser_contract():
    assert isinstance(viewer._load_grade_index('2025'),dict)


def test_center_credential_exports():
    from taiko_bot.offline import viewer_hiroba
    from taiko_bot.runtime.player.center.hiroba import credentials,sync
    assert viewer_hiroba.load_hiroba_credentials is credentials.load_hiroba_credentials
    assert viewer_hiroba.has_hiroba_credentials is credentials.has_hiroba_credentials
    assert viewer_hiroba.sync_hiroba_userdata is sync.sync_hiroba_userdata
    assert viewer_hiroba.discover_hiroba_playable_cards is sync.discover_hiroba_playable_cards


def test_no_legacy_imports():
    assert not any(name=='growth_compute' or name.startswith('plugins.utils') for name in sys.modules)


def test_credential_write_contract(monkeypatch):
    from taiko_bot.offline import viewer_hiroba
    from taiko_bot.runtime.player.center.hiroba import credentials
    from taiko_bot.runtime.player.center import taiko_db
    calls=[]
    class Cursor:
        def execute(self,sql,params):calls.append(('execute',params))
        def close(self):calls.append(('cursor-close',))
    class Connection:
        def cursor(self):return Cursor()
        def commit(self):calls.append(('commit',))
        def close(self):calls.append(('close',))
    monkeypatch.setattr(credentials,'ensure_hiroba_credentials_table',lambda:calls.append(('ensure',)))
    monkeypatch.setattr(credentials,'encrypt_password',lambda value:'encrypted:'+value)
    monkeypatch.setattr(taiko_db,'get_taiko_db_connection',Connection)
    viewer_hiroba.save_hiroba_credentials('123',' test@example.invalid ','secret',configured_by_qq=None)
    assert calls==[('ensure',),('execute',('123','test@example.invalid','encrypted:secret',None)),('commit',),('cursor-close',),('close',)]


def test_catalog_option_exports():
    from taiko_bot.offline import viewer_catalog
    from taiko_bot.runtime.player.center.progress_support import progress_catalog
    for name in ('available_pass_progress_keys', 'available_const_progress_keys', 'available_star_progress_values', 'load_active_song_ids', 'query_progress_items_by_pass_const', 'query_progress_items_by_const', 'query_progress_items_by_star'):
        assert getattr(viewer_catalog, name) is getattr(progress_catalog, name)


def test_native_continuation_large_stream():
    prefix=b'public legacy prefix!'
    checkpoint=SHA256().update(prefix).checkpoint()
    digest=NativeContinuation(checkpoint)
    reference=hashlib.sha256(prefix)
    chunk=b'x'*65536
    for _ in range(128):
        digest.update(chunk);reference.update(chunk)
    assert digest.hexdigest()==reference.hexdigest()
