"""One owned multi-source SH worker; Node owns the live SQL authority proof."""
import json
import logging
import signal
import sys
import types
from contextlib import ExitStack
from pathlib import Path

from taiko_store.reader import score_read_view
from taiko_store.merged_read import derive_merged_read, merge_rule_revision, MAX_BYTES


def read_message():
    raw = sys.stdin.buffer.readline(32769)
    if not raw.endswith(b"\n") or len(raw) > 32768:
        raise ValueError("Invalid protocol message")
    return json.loads(raw)


def reply(payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError("Output limit exceeded")
    print(raw, flush=True)


def main():
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.alarm(180)
    logging.disable(logging.CRITICAL)
    try:
        request = read_message()
        ids = request.get("sources")
        if not isinstance(ids, list) or not 2 <= len(ids) <= 128 or len(set(ids)) != len(ids) or any(not isinstance(item, str) or not item.isascii() or not item.isdigit() or not 1 <= len(item) <= 25 for item in ids):
            raise ValueError("Invalid source set")
        with ExitStack() as stack:
            views, manifest_bytes = {}, 0
            for identity in sorted(ids):
                view = stack.enter_context(score_read_view(request["root"], identity))
                manifest_bytes += len(json.dumps(view.manifest, separators=(",", ":")).encode())
                if manifest_bytes > MAX_BYTES:
                    raise ValueError("Manifest vector limit exceeded")
                views[identity] = view
            vector = []
            for identity in ids:
                publication = views[identity].publication
                if publication is None:
                    raise ValueError("Unmanaged source")
                vector.append({"identity": identity, **publication})
            reply({"ready": True, "schema": 1, "views": vector, "ruleRevision": merge_rule_revision()})
            derive = read_message()
            if derive == {"method": "finish"}:
                reply({"finished": True})
                return
            if derive != {"method": "derive"}:
                raise ValueError("Invalid derive message")
            payload = derive_merged_read(views, ids, request["profileSource"], request["kind"], raw_history=request.get("rawHistory") is True)
            reply({"ok": True, "payload": payload})
            if read_message() != {"method": "finish"}:
                raise ValueError("Invalid finish message")
            reply({"finished": True})
    except Exception:
        reply({"error": "merged_unavailable"})
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
