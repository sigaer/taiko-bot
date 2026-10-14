from __future__ import annotations

import os
import shlex
from pathlib import Path

DEFAULT_RUNTIME_ENV_FILE = Path("/etc/taiko-runtime.env")
_loaded = False


def load_runtime_environment(path: Path | None = None) -> None:
    """Load root-owned runtime secrets without overriding explicit environment values."""
    global _loaded
    if _loaded:
        return
    target = path or Path(
        os.getenv("TAIKO_RUNTIME_ENV_FILE", str(DEFAULT_RUNTIME_ENV_FILE))
    )
    if not target.exists():
        _loaded = True
        return
    file_stat = target.stat()
    if file_stat.st_uid != 0 or file_stat.st_mode & 0o077:
        raise RuntimeError(f"unsafe permissions on runtime environment file: {target}")
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        parsed = shlex.split(raw_value, comments=False, posix=True)
        value = parsed[0] if len(parsed) == 1 else raw_value.strip()
        os.environ.setdefault(key, value)
    _loaded = True
