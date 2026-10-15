"""Explicit, bounded backfill of missing daily v1 values. Never overwrite history.
Run under scripts/memory/run_qa.sh; accepts one user and an optional private seed
file of previously frozen Viewer values. No database access or private output.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from taiko_bot.offline.growth_compute import score
from taiko_bot.runtime.player.center.daily_ability import archive, archive_path, store_measurement, needs_measurement, local_time
from taiko_bot.runtime.player.center.snapshot_history import parse_snapshot_time
from taiko_store import PublicationStore, PublicationError
import os
import stat

MAX_SEED_BYTES = 8 * 1024**2


def read_seed(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SEED_BYTES:
            raise ValueError("Seed is not a bounded plain file")
        raw = stream.read(MAX_SEED_BYTES + 1)
    if len(raw) > MAX_SEED_BYTES:
        raise ValueError("Seed limit exceeded")
    rows = json.loads(raw)
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Seed record limit exceeded")
    return rows


def backfill(user, seed=None, *, userdata_dir=None):
    root = archive_path(user, userdata_dir=userdata_dir).parent.parent
    store = PublicationStore(root, str(user), max_file_bytes=32 * 1024**2)
    with store.shared():
        view = store.reader()
        if view.manifest is None:
            raise PublicationError("Backfill requires a canonical Source")
        files = [(parse_snapshot_time(Path(name), fallback_mtime=lambda name=name: view.file_times("history/" + name)["mtime"]), name)
                 for name in view.history_names()]
        files.sort()
        if len(files) > 10000:
            raise ValueError("Snapshot count exceeds bounded backfill limit")
        return _backfill(user, seed, store, view, files)


def _backfill(user, seed, store, view, files):
    names = {"big_song":"大歌力","stamina":"体力","speed":"高速处理","accuracy_power":"精度力","rhythm":"节奏处理","complex":"复合处理"}
    with archive(user, userdata_dir=store.root, publication_store=store) as days:
        before = len(days)
        if seed:
            for row in read_seed(seed):
                captured = dt.datetime.fromisoformat(row["capturedAt"])
                if local_time(captured).date().isoformat() in days:
                    continue
                dims = {label:row["dimensions"].get(key) for key,label in names.items()}
                if row["rating"] is not None and row["sampleCount"] > 0 and all(isinstance(v,(int,float)) for v in dims.values()):
                    store_measurement(days,captured,dims,row["rating"],row["sampleCount"],origin="existing-viewer-measurement")
        cfg = score.load_rating_config("./songs/rating_structured_with_ids.json")
        table = score.build_const_table(cfg["const_table"]["const_to_score"])
        # Replay a single evolving state; calculate only the final snapshot of
        # each missing day. Never retain a full snapshot list in memory.
        state, has_base, pending = {}, False, None
        def flush(captured):
            if captured is None or not needs_measurement(days,captured):
                return
            results = score._compute_results_from_userdata_records(list(state.values()),cfg,table,collapse_duplicate_versions=False)
            if results:
                store_measurement(days,captured,score.compute_dim_topN_means(results,20),score.aggregate_topN_value(results,"AI_rating",20),len(results),origin="historical-snapshot")
        for captured, name in files:
            if pending and pending.date() != captured.date():
                flush(pending)
            payload=json.loads(view.history_raw(name))
            meta=payload.get("_meta") or {}
            full=meta.get("full") or not meta and all(k in payload for k in ("songs","profile","achievement"))
            if full:
                state={};has_base=True
            if not has_base:
                continue
            for song in payload.get("songs",[]):
                state[(song.get("song_no"),song.get("level"))]=song
            for key in payload.get("songs_removed",[]):
                state.pop(tuple(key),None)
            pending=captured
        flush(pending)
        return {"daysBefore":before,"daysAfter":len(days),"filesRead":len(files)}


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument('--user',required=True)
    parser.add_argument('--seed')
    parser.add_argument('--userdata-dir')
    args=parser.parse_args()
    # Calculator diagnostics can include song labels. Keep operational output
    # bounded to aggregate counts, with all raw inputs staying on disk.
    import contextlib, os
    with open(os.devnull,'w') as quiet, contextlib.redirect_stdout(quiet):
        result=backfill(args.user,args.seed,userdata_dir=args.userdata_dir)
    print(json.dumps(result))
