#!/usr/bin/python3
"""Manage only the existing taiko screen's installed nb run process."""
import argparse
import fcntl
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
RUNTIME = Path('/home/sigaer/taiko')
CURRENT = Path('/opt/taiko-bot/current')
MODE_PATH = RUNTIME / 'runtime/bot-launch-mode'
HEALTH = 'http://127.0.0.1:37564/internal/bot-pool'


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=90)


def children(pid):
    try:
        return [int(item) for item in Path(f'/proc/{pid}/task/{pid}/children').read_text().split()]
    except FileNotFoundError:
        return []


def session():
    listing = run('screen', '-ls', check=False).stdout
    matches = re.findall(r'^\s*(\d+\.taiko)\s', listing, re.M)
    if len(matches) != 1:
        raise RuntimeError('Exactly one existing taiko screen required; create or select it first')
    shells = children(int(matches[0].split('.')[0]))
    if len(shells) != 1 or Path(f'/proc/{shells[0]}/comm').read_text().strip() != 'bash':
        raise RuntimeError('Expected the original single-window taiko bash session')
    return matches[0], shells[0]


def owned_nb(pid):
    try:
        args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return (Path(f'/proc/{pid}/cwd').resolve() == RUNTIME
                and b'run' in args
                and any(arg.startswith(b'/opt/taiko-bot/') and arg.endswith(b'/bin/nb') for arg in args))
    except FileNotFoundError:
        return False


def healthy():
    try:
        with urllib.request.urlopen(HEALTH, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def prepare():
    # Only a symlink and minimal nb metadata enter the data directory. Never
    # restore copied Bot implementations or expose runtime secret values.
    response = run(str(CURRENT / 'bin/python'), '-I', '-c',
                   'import json,sysconfig,taiko_bot; print(json.dumps({"entry":sysconfig.get_path("purelib")+"/bot.py","module":taiko_bot.__file__}))')
    installed = json.loads(response.stdout)
    for path in installed.values():
        if not Path(path).is_file() or not Path(path).resolve().is_relative_to('/opt/taiko-bot/releases'):
            raise RuntimeError('Expected a verified installed release')
    metadata = RUNTIME / 'pyproject.toml'
    template = (REPO / 'deploy/screen/pyproject.toml').read_bytes()
    if metadata.exists() and metadata.read_bytes() != template:
        raise RuntimeError('Runtime pyproject.toml has other content; refusing to overwrite')
    entry = RUNTIME / 'bot.py'
    target = Path(installed['entry'])
    if entry.is_symlink():
        if entry.readlink() != target:
            raise RuntimeError('Runtime entry has a different symlink target')
    elif entry.exists():
        raise RuntimeError('Runtime entry exists; refusing to overwrite user code')
    metadata.write_bytes(template)
    if not entry.is_symlink():
        entry.symlink_to(target)


def stop():
    name, shell = session()
    foreground = children(shell)
    if not foreground:
        print('taiko screen is idle')
        return
    if len(foreground) != 1 or not owned_nb(foreground[0]):
        raise RuntimeError('taiko screen has another foreground command; refusing to interrupt')
    # Snapshot the owned descendants before sending terminal Ctrl+C. Never use
    # a broad process kill or touch another screen/service.
    owned = set(foreground)
    pending = list(foreground)
    while pending:
        for child in children(pending.pop()):
            if child not in owned:
                owned.add(child)
                pending.append(child)
    identities = {pid: Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
                  for pid in owned if Path(f'/proc/{pid}/stat').exists()}
    run('screen', '-S', name, '-p', '0', '-X', 'stuff', '\x03')
    for _ in range(45):
        alive = []
        for pid, start in identities.items():
            try:
                if Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19] == start:
                    alive.append(pid)
            except FileNotFoundError:
                pass
        if not alive and not children(shell):
            print('taiko screen Bot and child processes stopped')
            return
        time.sleep(1)
    raise RuntimeError('taiko screen did not stop within 45 seconds; no fallback attempted')


def start():
    prepare()
    name, shell = session()
    if children(shell):
        raise RuntimeError('taiko screen is not idle; refusing a second Bot')
    run('systemctl', 'disable', '--now', 'taiko-bot')
    if run('ss', '-H', '-ltn', 'sport = :37564').stdout.strip():
        raise RuntimeError('Bot port still occupied; refusing a second Bot')
    # Record the selected mode before launching: later releases must keep it
    # even when startup fails. No silent switch back to systemd.
    MODE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODE_PATH.with_suffix('.next')
    temporary.write_text('screen\n')
    temporary.replace(MODE_PATH)
    command = 'source ' + shlex.quote(str(REPO / 'scripts/taiko_screen_env.sh')) + ' && nb run\n'
    run('screen', '-S', name, '-p', '0', '-X', 'stuff', command)
    for _ in range(45):
        foreground = children(shell)
        if len(foreground) == 1 and owned_nb(foreground[0]) and healthy():
            print(f'Taiko active in {name}: nb run; installed release {CURRENT.resolve().name}')
            return
        time.sleep(1)
    raise RuntimeError('screen nb run did not become healthy; inspect that screen, no fallback attempted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'start', 'stop'))
    args = parser.parse_args()
    with Path('/run/lock/taiko-screen.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        {'prepare': prepare, 'start': start, 'stop': stop}[args.action]()


if __name__ == '__main__':
    main()
