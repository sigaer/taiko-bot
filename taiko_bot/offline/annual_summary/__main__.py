from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .constants import DEFAULT_VERSION_KEY, RATING_DATA_PATH, SONG_DATA_PATH, USERDATA_DIR
from .finaltitle_reference_cli import build_finaltitle_reference
from .helpers import iso_datetime
from .service import build_annual_result
from .ratings import build_rating_distribution
from .shadow import build_shadow_report
from .profiling import mark_profile_stage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m taiko_bot.offline.annual_summary")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "events"):
        command = subparsers.add_parser(name)
        command.add_argument("--taiko-id", required=True)
        command.add_argument("--allow-current-archive", action="store_true")
        command.add_argument("--version", default=DEFAULT_VERSION_KEY)
        command.add_argument("--version-json", required=True)
        command.add_argument("--userdata-dir", default=str(USERDATA_DIR))
        command.add_argument("--song-data", default=str(SONG_DATA_PATH))
        command.add_argument("--rating-data", default=str(RATING_DATA_PATH))
        command.add_argument("--generated-at")
        command.add_argument("--output", default="-")
    ratings = subparsers.add_parser("ratings")
    ratings.add_argument("--userdata-dir", default=str(USERDATA_DIR))
    ratings.add_argument("--rating-data", default=str(RATING_DATA_PATH))
    ratings.add_argument("--song-data", default=str(SONG_DATA_PATH))
    ratings.add_argument("--generated-at")
    ratings.add_argument("--output", default="-")
    reference = subparsers.add_parser("finaltitle-reference")
    reference.add_argument("--summaries-dir", required=True)
    reference.add_argument("--userdata-dir", default=str(USERDATA_DIR))
    reference.add_argument("--generated-at")
    reference.add_argument("--source", default="")
    reference.add_argument("--output", default="-")
    shadow = subparsers.add_parser("shadow")
    shadow.add_argument("--version", default=DEFAULT_VERSION_KEY)
    shadow.add_argument("--version-json", required=True)
    shadow.add_argument("--userdata-dir", default=str(USERDATA_DIR))
    shadow.add_argument("--generated-at")
    shadow.add_argument("--output", default="-")
    return parser


def _write_output(payload: Dict[str, Any], output: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if output == "-":
        sys.stdout.write(serialized)
        mark_profile_stage("serialization_complete", serializedBytes=len(serialized.encode("utf-8")))
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    mark_profile_stage("serialization_complete", serializedBytes=path.stat().st_size)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    generated_at = datetime.fromisoformat(args.generated_at) if args.generated_at else None
    if args.command == "ratings":
        _write_output(
            build_rating_distribution(
                args.userdata_dir,
                args.rating_data,
                generated_at=generated_at,
            ),
            args.output,
        )
        return 0
    if args.command == "finaltitle-reference":
        _write_output(
            build_finaltitle_reference(
                args.summaries_dir,
                args.userdata_dir,
                generated_at=iso_datetime(generated_at) if generated_at else None,
                source=args.source,
            ),
            args.output,
        )
        return 0
    if args.command == "shadow":
        _write_output(
            build_shadow_report(
                args.userdata_dir,
                json.loads(args.version_json),
                generated_at=generated_at,
            ),
            args.output,
        )
        return 0
    def report(stage: str, percent: int, detail: Dict[str, Any]) -> None:
        sys.stderr.write(json.dumps({"annualProgress": True, "stage": stage, "percent": percent, "detail": detail}, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stderr.flush()

    version = json.loads(args.version_json)
    result = build_annual_result(
        args.taiko_id,
        version,
        userdata_dir=args.userdata_dir,
        song_data_path=args.song_data,
        rating_path=args.rating_data,
        generated_at=generated_at,
        progress=report,
        allow_current_archive=args.allow_current_archive,
    )
    if args.command == "events":
        payload = {"events": result["events"], "provenance": result["summary"]["provenance"]}
    else:
        payload = result
    _write_output(payload, args.output)
    mark_profile_stage("process_exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
