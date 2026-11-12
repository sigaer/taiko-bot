"""One-shot, staged OurTaiko import. No player data or assets are rewritten."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone

from .ourtaiko_catalog import atomic_json, refresh_catalog
from .paths import root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root())
    parser.add_argument("--cached", action="store_true")
    parser.add_argument("--write", action="store_true", help="Publish after reviewing the staged catalog")
    args = parser.parse_args()
    catalog = args.root / "songs/song_data.json"
    songs = json.loads(catalog.read_text(encoding="utf-8"))
    if args.write:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = args.root / "songs/recovery_backups" / f"ourtaiko-{stamp}"
        backup.mkdir(parents=True, exist_ok=False)
        for name in ("song_data.json", "song_data_raw.json", "song_id2tjapath.json", "ourtaiko_charts.json",
                     "song_alias.json", "song_alias_new.json", "song_score.json", "taiko_goku_onis.json",
                     "rating_structured_with_ids.json", "catalog_constants.json", "constants_id_v2.csv",
                     "branch_audio_manifest.json", "song_difficulty.json", "cn_song_positions.json",
                     "analyze_result_filtered.json"):
            source = catalog.parent / name
            if source.is_file():
                shutil.copy2(source, backup / name)
    merged = refresh_catalog(songs, root=args.root, fetch=not args.cached, persist=args.write)
    target = catalog if args.write else args.root / "songs/song_data.ourtaiko-staged.json"
    atomic_json(target, merged)
    print(json.dumps({"songs": len(merged), "output": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
