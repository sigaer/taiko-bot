"""Private bounded stdin worker; not an HTTP/unauthenticated sync gateway."""
import json
import sys
import signal
import pymysql
import types
from pathlib import Path

# This private CLI loads real leaf modules without the Bot plugin registry or
# the aggregate utils initializer (which preloads drawing/catalog services).

from taiko_bot.runtime.player.center.taiko_db import _db_config
from taiko_bot.runtime.player.center.account_sync import AccountSyncError, run_account_sync


def main():
    # Independent kernel lifetime: still expires if the Viewer parent exits.
    # Signal death releases native SQL/file locks; registered publication
    # pending is recovered by the next admitted Source operation.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.alarm(180)
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise AccountSyncError(400, "invalid_request", "同步请求内容无效。")
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeError):
            raise AccountSyncError(400, "invalid_request", "同步请求内容无效。") from None
        # Captured configuration is supplied by the actual application's pool.
        config = _db_config()
        factory = lambda: pymysql.connect(**config, connect_timeout=5, read_timeout=45, write_timeout=45)
        result = run_account_sync(request, connection_factory=factory)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")))
    except AccountSyncError as error:
        print(json.dumps({"ok": False, "status": error.status, "error": error.code, "message": error.message, "data": error.data}, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        print('{"ok":false,"status":503,"error":"sync_unavailable","message":"同步服务暂不可用，请稍后重试。"}')
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
