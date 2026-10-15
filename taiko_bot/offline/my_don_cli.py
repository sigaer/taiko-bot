from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence

from taiko_bot.runtime.player.center.draw_dress import MY_DON_SHOWCASE_LAYOUTS, render_my_don_image
from taiko_bot.runtime.player.center.song_title_showcase import (
    list_song_title_showcase_candidates,
    serialize_showcase_titles,
)


def _read_userdata(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("userdata root must be an object")
    return payload


def _run_candidates(args: argparse.Namespace) -> int:
    userdata = _read_userdata(Path(args.userdata))
    payload = serialize_showcase_titles(
        list_song_title_showcase_candidates(userdata.get("songs") or [])
    )
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


def _run_render(args: argparse.Namespace) -> int:
    taiko_id = str(args.taiko_id or "").strip()
    if not re.fullmatch(r"[0-9]{1,25}", taiko_id):
        raise ValueError("taiko id must contain 1 to 25 digits")
    title_overrides = None
    if args.title_overrides_json:
        decoded = json.loads(args.title_overrides_json)
        if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
            raise ValueError("title overrides must be a JSON string array")
        title_overrides = decoded
    sys.stdout.buffer.write(
        render_my_don_image(
            taiko_id,
            title_overrides=title_overrides,
            showcase_layout=args.showcase_layout,
        )
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MyDon viewer integration CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    candidates = subparsers.add_parser("candidates")
    candidates.add_argument("--userdata", required=True)
    candidates.set_defaults(handler=_run_candidates)

    render = subparsers.add_parser("render")
    render.add_argument("--taiko-id", required=True)
    render.add_argument("--title-overrides-json")
    render.add_argument(
        "--showcase-layout",
        choices=sorted(MY_DON_SHOWCASE_LAYOUTS),
        default="nickname",
    )
    render.set_defaults(handler=_run_render)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
