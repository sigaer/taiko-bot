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
    merged = refresh_catalog(songs, root=args.root, fetch=not args.cached)
    target = catalog if args.write else args.root / "songs/song_data.ourtaiko-staged.json"
    if args.write:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = args.root / "songs/recovery_backups" / f"ourtaiko-{stamp}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(catalog, backup)
    atomic_json(target, merged)
    print(json.dumps({"songs": len(merged), "output": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
