from dataclasses import replace
import os
import time
from taiko_bot.runtime.player.center import taikob_v2_data as source


def test_unexpired_v2_snapshot_observes_local_catalog_replacement(tmp_path,monkeypatch):
    header='id,title,difficulty,totalNotes,sub_constant_1,main_constant,sub_constant_2,stamina,handspeed,burst,complex,rhythm\n'
    path=tmp_path/'constants_id_v2.csv'
    path.write_text(header+'1,Public Chart,oni,600,9,10.2,11,8,9,10,11,12\n')
    source.clear_v2_source_cache()
    monkeypatch.setattr(source,'V2_DATASET_FALLBACK_PATH',path)
    monkeypatch.setattr(source,'_start_background_refresh_locked',lambda now:None)
    first=source.load_v2_snapshot()
    source._snapshot=replace(first,loaded_at_monotonic=time.monotonic())
    stamp=path.stat().st_mtime_ns
    path.write_text(header+'1,Public Chart,oni,600,9,11.2,11,8,9,10,11,12\n')
    os.utime(path,ns=(stamp,stamp))
    second=source.load_v2_snapshot()
    assert second.revision!=first.revision
    assert second.song_map[(1,4)].main_constant==11.2
    assert source.load_v2_snapshot() is second
    source.clear_v2_source_cache()
