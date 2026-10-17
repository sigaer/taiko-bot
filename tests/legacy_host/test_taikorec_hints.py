from __future__ import annotations

import importlib
import re

import nonebot


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    nonebot.require("taiko_bot.runtime.player.entry")
    return importlib.import_module("taiko_bot.runtime.player.center.helpers")


def _missing_hint(source):
    from taiko_bot.runtime.player.center.tinfo_provider import TinfoHostProvider
    provider = TinfoHostProvider.__new__(TinfoHostProvider)
    class StopBeforeRead(Exception): pass
    calls=[]
    def snapshot(*args):
        calls.append(args)
        if len(calls)>1: raise StopBeforeRead()
        return [], {'current_slot':1,'current_index':0,'ids':['synthetic'],'sources':{'synthetic':source}}, 'observation'
    provider._snapshot=snapshot
    try: provider.prepare('actor','principal')
    except StopBeforeRead: pass
    else: raise AssertionError('test must stop before private IO')
    return provider.recommendation_missing_hint


def test_build_missing_userdata_upload_hint_uses_hiroba_update():
    text = _missing_hint('hiroba')
    assert '更新hiroba' in text
    assert 'taikoupdate' not in text


def test_build_missing_userdata_upload_hint_uses_taikoupdate_for_wahlap():
    assert 'taikoupdate' in _missing_hint('wahlap')


def test_taikorec_command_alias_accepts_song_recommend():
    taiko = _load_taiko_module()
    runtime = nonebot.require("taiko_bot.runtime.player.entry").recommendation
    request = runtime.parse("歌曲推荐 体力 9星")
    assert re.fullmatch(rf"(?:{runtime.ALIASES}).*", "歌曲推荐 体力 9星", re.IGNORECASE)
    assert request.dimension == "体力"
    assert request.limit == 20
    assert not hasattr(taiko, "taikorec")
