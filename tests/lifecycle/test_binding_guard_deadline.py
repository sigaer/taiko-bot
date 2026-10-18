"""Long synchronization replies still prove live SQL bindings, without a stale query deadline."""
import ast
import asyncio
from pathlib import Path
from importlib.util import find_spec
from types import SimpleNamespace

import pytest
from taiko_bot.runtime.player.authority import AuthorizedDelivery, TinfoDenied, TinfoUnavailable
from taiko_bot.runtime.player.center import tinfo_provider


def binding_guard():
    path = Path(find_spec('taiko_bot.runtime.player.lifecycle_authority').origin)
    node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'BindingGuard')
    namespace = {'TinfoDenied': TinfoDenied, 'AuthorizedDelivery': AuthorizedDelivery}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


@pytest.fixture
def bindings(monkeypatch):
    clock = [0.0]
    actor = 'qq_official:synthetic'
    state = {'rows': [(1, actor, '123456789012', 1, 1, 'hiroba', 1)], 'virtual': 0, 'reads': 0}
    monkeypatch.setattr(tinfo_provider.time, 'monotonic', lambda: clock[0])

    class Cursor:
        def execute(self, sql, params):
            assert params == (actor,)
            assert 'FOR UPDATE' not in sql
        def fetchall(self):
            state['reads'] += 1
            return list(state['rows'])
        def fetchone(self):
            return (actor, state['virtual'])
        def close(self):
            pass

    class Connection:
        def cursor(self):
            return Cursor()
        def commit(self):
            pass
        def close(self):
            pass

    def provider():
        return tinfo_provider.TinfoHostProvider(connection_factory=Connection, userdata_root='/var/tmp/no-score-io')

    namespace = binding_guard()
    namespace['entry'] = SimpleNamespace(profile=lambda: 'center', create_provider=provider)
    return SimpleNamespace(clock=clock, state=state, actor=actor, guard=namespace['BindingGuard'], provider=provider)


def test_progress_and_success_after_four_minutes_recheck_unchanged_bindings(bindings):
    sent = []
    class Matcher:
        async def send(self, text):
            sent.append(text)
        async def finish(self, text):
            sent.append(text)
    guard = bindings.guard(bindings.actor)
    delivery = guard.delivery(Matcher())
    async def run():
        bindings.clock[0] = 109
        await delivery.send('Half complete')
        bindings.clock[0] = 240
        await delivery.finish('Update complete')
    asyncio.run(run())
    assert sent == ['Half complete', 'Update complete']
    assert bindings.state['reads'] == 3


@pytest.mark.parametrize('change', ['selection', 'remove', 'visibility', 'virtual'])
def test_changed_binding_still_denies_a_late_reply(bindings, change):
    guard = bindings.guard(bindings.actor)
    bindings.clock[0] = 240
    row = list(bindings.state['rows'][0])
    if change == 'selection':
        row[4] = 0
    elif change == 'visibility':
        row[6] = 0
    elif change == 'remove':
        bindings.state['rows'] = []
    else:
        bindings.state['virtual'] = 1
    if change not in ('remove', 'virtual'):
        bindings.state['rows'] = [tuple(row)]
    with pytest.raises(TinfoDenied):
        guard.verify_initial()


def test_score_query_absolute_deadline_is_preserved(bindings):
    provider = bindings.provider()
    bindings.clock[0] = 121
    with pytest.raises(TinfoUnavailable):
        provider._snapshot(bindings.actor, bindings.actor)
