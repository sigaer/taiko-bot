"""Bounded local pipe protocol for non-Python center adapters.

No listener or credentials. One child owns one kernel lease; EOF, deadline or
process death releases it. Raw inputs travel over stdin, never command text.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys

from .publication import PublicationStore, PublicationError

MAX_MESSAGE_BYTES = 32 * 1024**2


def send(value):
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode()) > MAX_MESSAGE_BYTES:
        raise PublicationError("Publication bridge response limit exceeded")
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def deadline(_signum, _frame):
    raise TimeoutError("Publication bridge lifetime exceeded")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--mode", choices=("read", "write"), required=True)
    parser.add_argument("--lifetime", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.lifetime <= 900:
        parser.error("lifetime must be 1..900 seconds")
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(args.lifetime)
    store = PublicationStore(args.root, args.identity)
    lease = store.shared() if args.mode == "read" else store.exclusive()
    staged = {}
    try:
        with lease:
            if args.mode == "write":
                store.collect()
            send({"ready": True, "schema": store.schema, "view": store.view()})
            while True:
                raw = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
                if not raw:
                    return 0
                if len(raw) > MAX_MESSAGE_BYTES:
                    raise PublicationError("Publication bridge input limit exceeded")
                message = json.loads(raw)
                method = message.get("method")
                if method == "finish":
                    send({"finished": True})
                    return 0
                if method == "file-times":
                    if staged:
                        raise PublicationError("Staged metadata is unavailable")
                    send({"times": store.reader().file_times(message.get("key"))})
                    continue
                if args.mode != "write":
                    raise PublicationError("Read lease does not accept mutations")
                if method == "put":
                    key, body = message.get("key"), message.get("body")
                    store._projection_path(key)
                    if not isinstance(body, str):
                        raise PublicationError("Publication body requires text")
                    encoded = body.encode()
                    history_count = sum(name.startswith("history/") for name in staged)
                    if key.startswith("history/") and key not in staged:
                        history_count += 1
                    history_bytes = sum(value["bytes"] for name, value in staged.items()
                                        if name.startswith("history/") and value is not None and name != key)
                    if key.startswith("history/"):
                        history_bytes += len(encoded)
                    if history_count > store.max_history_files or history_bytes > store.max_history_bytes:
                        raise PublicationError("Publication staged batch limit exceeded")
                    staged[key] = store.stage(encoded)
                    send({"staged": True, "reference": staged[key]})
                elif method == "remove":
                    key = message.get("key")
                    store._projection_path(key)
                    staged[key] = None
                    send({"staged": True})
                elif method == "publish":
                    view = store.publish(staged, replace_history=message.get("replaceHistory") is True,
                                         transaction_id=message.get("transactionId"))
                    staged.clear()
                    send({"published": True, "view": view})
                elif method == "backup":
                    if staged:
                        raise PublicationError("Cannot back up a staged mutation")
                    from .backup import export_source_backup
                    backup = export_source_backup(store, message.get("backupKey"))
                    send({"backedUp": True, "backupKey": backup["backupKey"], "source": {"sequence": backup["source"]["sequence"], "commitId": backup["source"]["commitId"]}, "view": store.view()})
                elif method == "purge-archives":
                    from .backup import purge_backup_archives
                    send({"purged": purge_backup_archives(store, message.get("backupKey"))})
                elif method == "verify-backup":
                    if staged:
                        raise PublicationError("Cannot verify a staged mutation")
                    from .backup import verify_source_backup
                    backup = verify_source_backup(store, message.get("backupKey"))
                    send({"verified": True, "backupKey": backup["backupKey"], "source": {"sequence": backup["source"]["sequence"], "commitId": backup["source"]["commitId"]}})
                elif method == "restore-backup":
                    if staged:
                        raise PublicationError("Cannot restore a staged mutation")
                    from .backup import restore_source_backup
                    restore_source_backup(store, message.get("backupKey"), transaction_id=message.get("transactionId"))
                    send({"restored": True, "backupKey": message.get("backupKey"), "view": store.view()})
                elif method == "collect":
                    if staged:
                        raise PublicationError("Cannot collect a staged batch")
                    send({"collected": store.collect()})
                else:
                    raise PublicationError("Unknown publication method")
    except Exception as error:
        # Never include raw payloads, paths, IDs, exception repr or traceback.
        send({"error": "PUBLICATION_FAILURE", "kind": type(error).__name__})
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
