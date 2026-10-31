"""Private local diagnostics; never emits cache keys, row values or credentials."""
import json
import os
import re
import threading
import time
import weakref
from pathlib import Path

_registry = {}
_lock = threading.RLock()
_started = False


def register_cache(cache):
    with _lock:
        _registry[cache.name] = weakref.ref(cache)
    return cache


def snapshot(service):
    fields = {}
    for name in ('status', 'smaps_rollup'):
        try:
            for line in Path('/proc/self', name).read_text().splitlines():
                match = re.match(r'^(VmRSS|Pss|VmSwap|RssAnon|RssFile):\s+(\d+)', line)
                if match:
                    fields[match[1] + '_kib'] = int(match[2])
        except OSError:
            pass
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    start_ticks = int(Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19])
    with _lock:
        live = {}
        for name, ref in _registry.items():
            cache = ref()
            if cache is not None:
                live[name] = cache
        for name in list(_registry):
            if name not in live:
                del _registry[name]
    return dict(at=time.time(), service=service, pid=os.getpid(), uptime_seconds=uptime-start_ticks/os.sysconf('SC_CLK_TCK'),
                process=fields, caches=[value.snapshot() for value in live.values()])


def start_telemetry(service, directory='/var/log/python-memory', interval=60):
    global _started
    if not re.fullmatch(r'[a-z0-9_-]+', service):
        raise ValueError('invalid metric service identifier')
    with _lock:
        if _started:
            return
        _started = True
    def emit():
        root = Path(os.getenv('PYTHON_MEMORY_METRICS_DIR', directory)) / service
        while True:
            try:
                root.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = root / (str(os.getpid()) + '.json')
                temporary = root / (str(os.getpid()) + '.tmp')
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump(snapshot(service), stream, separators=(',', ':'))
                os.replace(temporary, target)
            except Exception as error:
                print('[memory-metrics]', type(error).__name__, flush=True)
            time.sleep(max(10, interval))
    threading.Thread(target=emit, name='memory-metrics', daemon=True).start()
