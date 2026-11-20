"""Daily title catalog, ID-enriched relations and local title API publication."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import subprocess
import sys

from .paths import root

logger = logging.getLogger(__name__)


def refresh_title_relations(*, runtime_root: Path | None = None, cached=False, apply=True):
    runtime_root = runtime_root or root()
    catalog = runtime_root / "data/title_catalog_cache.json"
    if not cached:
        from taiko_bot.services.title_catalog import refresh_title_catalog_cache
        items = refresh_title_catalog_cache()
        if not items:
            raise ValueError("Official title catalog refresh failed")
    else:
        items = json.loads(catalog.read_text(encoding="utf-8")).get("titles", [])
        if not items:
            raise ValueError("Official title catalog cache is empty")
    viewer = runtime_root / "taiko-forum/taiko_viewer"
    relations = viewer / "assets/data/title_song_relations.json"
    subprocess.run([
        sys.executable, str(viewer / "scripts/extract_title_song_relations.py"),
        "--input", str(viewer / "assets/data/title_wikitable.json"),
        "--output", str(relations), "--title-catalog", str(catalog),
        "--songs", str(runtime_root / "songs/song_data.json"),
    ], check=True, timeout=90, cwd=viewer)
    command = [sys.executable, str(viewer / "scripts/sync_title_song_relations.py"),
               "--relations", str(relations), "--config", str(runtime_root / "data/title_sync.json")]
    if apply:
        command.append("--apply")
    subprocess.run(command, check=True, timeout=330, cwd=viewer)
    logger.info("Title relations generated and local API synchronization completed (apply=%s)", apply)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cached", action="store_true", help="Use the last official title catalog")
    parser.add_argument("--apply", action="store_true", help="Publish through authenticated management API")
    args = parser.parse_args()
    refresh_title_relations(cached=args.cached, apply=args.apply)


if __name__ == "__main__":
    main()
