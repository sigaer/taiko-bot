#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


from taiko_bot.runtime.player.center.hiroba.client import HirobaClient
from taiko_bot.runtime.player.center.hiroba.parser import (
    enumerate_fetch_tasks,
    filter_song_refs_by_levels,
    merge_song_refs,
    parse_score_list_page,
)
from taiko_bot.runtime.player.center.hiroba.sync import resolve_hiroba_sync_levels, sync_hiroba_userdata


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Donder Hiroba scores into taiko userdata")
    parser.add_argument("--email", default=os.getenv("HIROBA_EMAIL", ""))
    parser.add_argument("--password", default=os.getenv("HIROBA_PASSWORD", ""))
    parser.add_argument("--taiko-no", default="")
    parser.add_argument("--token", default=os.getenv("HIROBA_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument(
        "--levels",
        default=os.getenv("HIROBA_SYNC_LEVELS", "4,5"),
        help="Comma-separated difficulty levels to sync, e.g. 4,5 or all",
    )
    args = parser.parse_args()
    levels_text = str(args.levels).strip().lower()
    if levels_text in {"all", "*"}:
        sync_levels = {1, 2, 3, 4, 5}
    elif not levels_text:
        sync_levels = resolve_hiroba_sync_levels(None)
    else:
        sync_levels = {
            int(part.strip())
            for part in str(args.levels).split(",")
            if part.strip()
        }

    if not args.dry_run and not args.token and (not args.email or not args.password):
        print("HIROBA_EMAIL/HIROBA_PASSWORD or --token is required.", file=sys.stderr)
        return 2

    if args.dry_run and not args.token and (not args.email or not args.password):
        print("HIROBA_EMAIL and HIROBA_PASSWORD are required for dry-run.", file=sys.stderr)
        return 2

    if args.dry_run:
        client = HirobaClient(token=args.token or None)
        if not args.token:
            client.login(args.email, args.password)
        client.update_score()
        pages = [parse_score_list_page(client.fetch_score_list(g)) for g in range(1, 9)]
        merged = merge_song_refs(pages)
        filtered = (
            filter_song_refs_by_levels(merged, sync_levels)
            if sync_levels
            else merged
        )
        tasks = enumerate_fetch_tasks(filtered, levels=sync_levels)
        print(
            f"played_songs={len(filtered)} charts={len(tasks)} "
            f"levels={sorted(sync_levels) if sync_levels else 'all'}"
        )
        return 0

    def _progress(message: str, *, force: bool = False) -> None:
        print(message, flush=True)

    taiko_no = sync_hiroba_userdata(
        args.email or None,
        args.password or None,
        taiko_no=args.taiko_no or None,
        token=args.token or None,
        levels=sync_levels,
        max_workers=max(1, args.max_workers),
        progress=_progress,
    )
    print(f"Saved userdata/{taiko_no}data.json")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
