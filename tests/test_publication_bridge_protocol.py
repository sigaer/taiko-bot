"""Cold import diagnostics must never enter the publication JSON channel."""
import builtins
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from taiko_store import bridge

MODULE = 'taiko_bot.runtime.player.center.daily_ability'


@pytest.mark.parametrize('failure', [None, 'import', 'capture'])
def test_capture_redirects_import_and_computation_diagnostics(monkeypatch, capsys, failure):
    real_import = builtins.__import__
    calls = []

    def capture(*args, **kwargs):
        print('synthetic computation diagnostic')
        calls.append((args, kwargs))
        if failure == 'capture':
            raise ValueError('synthetic-private-exception-payload')

    def noisy_import(name, *args, **kwargs):
        if name == MODULE:
            print('synthetic cold import diagnostic')
            if failure == 'import':
                raise ImportError('synthetic-private-exception-payload')
            return SimpleNamespace(capture_snapshot=capture)
        return real_import(name, *args, **kwargs)

    store = SimpleNamespace(identity='111', root=Path('/synthetic'),
                            reader=lambda: SimpleNamespace(decoded=lambda: {'songs': []}))
    monkeypatch.setattr(builtins, '__import__', noisy_import)
    bridge.capture_current_measurement(store)
    output = capsys.readouterr()
    assert output.out == ''
    assert 'synthetic cold import diagnostic' in output.err
    assert 'synthetic-private-exception-payload' not in output.err
    if failure != 'import':
        assert calls[0][0][:2] == ('111', [])
        assert calls[0][1]['publication_store'] is store
        assert 'synthetic computation diagnostic' in output.err
    if failure:
        assert 'Daily measurement unavailable (' in output.err


@pytest.mark.parametrize('failure', [None, 'import', 'capture'])
def test_cold_pipe_first_publish_nonce_retry_and_delete(tmp_path, failure):
    # A new interpreter has no warmed model/import cache. Only the derived
    # measurement import is replaced; the bridge and storage remain real.
    bootstrap = r'''
import builtins,json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from taiko_store import bridge
root=Path(sys.argv[2]);failure=sys.argv[3]
real_import=builtins.__import__
def capture(*args,**kwargs):
    print('synthetic calculation noise')
    with (root/'capture-count').open('a') as out: out.write('called\n')
    if failure=='capture':raise ValueError('synthetic-private-exception-payload')
def noisy_import(name,*args,**kwargs):
    if name=='taiko_bot.runtime.player.center.daily_ability':
        print('synthetic first import noise')
        if failure=='import':raise ImportError('synthetic-private-exception-payload')
        return SimpleNamespace(capture_snapshot=capture)
    return real_import(name,*args,**kwargs)
builtins.__import__=noisy_import
sys.argv=['bridge','--root',str(root),'--identity','111','--mode','write','--lifetime','10']
raise SystemExit(bridge.main())
'''
    messages = [
        {'method': 'put', 'key': 'current', 'body': '{"songs":[]}'},
        {'method': 'publish', 'transactionId': 'a' * 32},
        {'method': 'put', 'key': 'current', 'body': '{"songs":[]}'},
        {'method': 'publish', 'transactionId': 'a' * 32},
        {'method': 'remove', 'key': 'current'},
        {'method': 'publish', 'transactionId': 'b' * 32},
        {'method': 'finish'},
    ]
    process = subprocess.run(
        [sys.executable, '-I', '-c', bootstrap,
         str(Path(bridge.__file__).resolve().parent.parent), str(tmp_path), failure or 'none'],
        input=''.join(json.dumps(row) + '\n' for row in messages),
        text=True, capture_output=True, timeout=15, cwd=tmp_path,
    )
    assert process.returncode == 0
    # Parsing every line is intentional: ignoring a noisy line would conceal
    # exactly the production protocol failure this test must catch.
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(replies) == len(messages) + 1
    assert replies[0]['ready'] and replies[-1]['finished']
    assert all('error' not in row for row in replies)
    publications = [row['view'] for row in replies if row.get('published')]
    assert [row['sequence'] for row in publications] == [1, 1, 2]
    assert publications[0]['commitId'] == publications[1]['commitId'] == 'a' * 32
    assert publications[-1]['commitId'] == 'b' * 32
    assert 'current' not in publications[-1]['files']
    assert 'synthetic first import noise' in process.stderr
    assert 'synthetic-private-exception-payload' not in process.stderr
    count = tmp_path / 'capture-count'
    assert (count.read_text().splitlines() if count.exists() else []) == (
        [] if failure == 'import' else ['called'])
