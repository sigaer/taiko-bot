"""Private stdin-only Hiroba discovery/crypto; no DB or score mutation."""
import json
import logging
import signal
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

from taiko_bot.runtime.player.center.hiroba.private_credentials import run_private_credentials, CredentialWorkerError


class Discard:
    def write(self, value): return len(value)
    def flush(self): pass


def main(*, discovery=None):
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.alarm(30)
    logging.disable(logging.CRITICAL)
    try:
        raw = sys.stdin.buffer.read(32769)
        if len(raw) > 32768:
            raise CredentialWorkerError(400, "invalid_request")
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeError):
            raise CredentialWorkerError(400, "invalid_request") from None
        if isinstance(request, dict) and request.get("mode") == "discover":
            signal.alarm(180)
        with redirect_stdout(Discard()):
            result = run_private_credentials(request, discovery=discovery)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, separators=(",", ":")))
    except CredentialWorkerError as error:
        print(json.dumps({"ok": False, "status": error.status, "error": error.code}, separators=(",", ":")))
    except Exception:
        print('{"ok":false,"status":503,"error":"credential_unavailable"}')
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
