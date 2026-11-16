"""The actual handler must yield during input and render, and recheck delivery."""
import ast
import asyncio
from pathlib import Path
from threading import get_ident
import time
from types import SimpleNamespace

import pytest
from taiko_bot.runtime.player.authority import TinfoDenied, TinfoUnavailable, AuthorizedDelivery
from taiko_bot.runtime.player.render_executor import RenderExecutor, RenderBusy
from taiko_bot.runtime.player.render_resources import request_resources


@pytest.mark.parametrize("profile", ["center", "client"])
@pytest.mark.parametrize("revoked", [False, True])
def test_progress_runs_blocking_stages_off_loop_and_never_sends_after_revocation(revoked, profile, monkeypatch):
    if profile == "client":
        from taiko_bot import public_data
        monkeypatch.setattr(public_data, "ensure_asset_resource_available", lambda *a, **kw:(True, ""))
    async def scenario():
        main = get_ident()
        threads, delivered, replies = [], [], []
        state = {"allowed": True}
        inputs, renders = RenderExecutor(1), RenderExecutor(1)
        private = SimpleNamespace(current={}, history=(), current_failure=None,
            authorized_target=SimpleNamespace(user_id="111"))
        class Provider:
            def prepare(self, *a, **kw):
                threads.append(get_ident())
                time.sleep(.03)
                return private
            def verify(self, value):
                assert get_ident() == main and value is private
                if not state["allowed"]:
                    raise TinfoDenied()
        provider = Provider()
        def execute(*a):
            threads.append(get_ident())
            time.sleep(.03)
            state["allowed"] = not revoked
            return "synthetic-result"
        async def deliver(delivery, event, result):
            delivery._verify()
            delivered.append(result)
        async def reply(*args):
            replies.append(args[-1])
        helper = SimpleNamespace(_normalize_identity_key=lambda x:x,
            get_identity_key=lambda **kw:"onebot_v11:1",
            _resolve_requested_identity_key=lambda e:("onebot_v11:1",True),
            _finish_text_reply=reply)
        entry = SimpleNamespace(helpers=helper, create_provider=lambda:provider,
            TinfoDenied=TinfoDenied, TinfoUnavailable=TinfoUnavailable,
            MergedBindError=ValueError, AuthorizedDelivery=AuthorizedDelivery, deliver=deliver)
        path = Path(__file__).resolve().parents[2]/"taiko_bot/runtime/player/progress.py"
        function = next(n for n in ast.parse(path.read_text()).body if getattr(n,"name","") == "progress_handle")
        function.decorator_list = []
        ns = dict(prepare_progress=lambda *a:("6星进度",1),CommandContext=lambda **kw:kw,
            extract_match=lambda e:None,CommandResult=type("Result",(),{}),entry=entry,
            modules=lambda:(SimpleNamespace(BASE=Path("/synthetic")),SimpleNamespace(
                parse_dani_progress_request=lambda t:None,DOJO_DATA_VERSION="2026",
                CURRENT_DANI_VERSION="2025",DOJO_VERSIONS={"2026"}),None),
            PROFILE=profile,input_executor=inputs,executor=renders,RenderBusy=RenderBusy,
            thaw=lambda x:x,build_ports=lambda *a:None,execute_progress=execute,
            request_resources=request_resources)
        tree = ast.Module(body=[ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0),function],type_ignores=[])
        exec(compile(ast.fix_missing_locations(tree),str(path),"exec"),ns)
        ticks=0
        async def heartbeat():
            nonlocal ticks
            while True:
                ticks+=1
                await asyncio.sleep(.002)
        ticker=asyncio.create_task(heartbeat())
        try:
            await ns["progress_handle"](object(),object())
            assert len(threads)==2 and all(t!=main for t in threads)
            assert ticks>=5
            assert delivered == ([] if revoked else ["synthetic-result"])
            assert bool(replies) == revoked
        finally:
            ticker.cancel()
            await asyncio.gather(ticker,return_exceptions=True)
            await inputs.shutdown()
            await renders.shutdown()
        assert not inputs._active and not renders._active
    asyncio.run(scenario())


def test_real_native_provider_owns_connections_and_leases_inside_input_worker(tmp_path):
    import json
    from taiko_store import PublicationStore
    from taiko_bot.runtime.player.center.tinfo_provider import TinfoHostProvider
    principal = "onebot_v11:12345"
    state = {"visible":1}
    connections = []
    class Connection:
        def __init__(self):
            self.owner = get_ident()
            self.closed = False
            connections.append(self)
        def cursor(self):
            return self
        def execute(self, sql, args):
            assert get_ident() == self.owner and sql.startswith("SELECT")
        def fetchall(self):
            return [(1, principal, "111", 1, 1, "wahlap", state["visible"])]
        def fetchone(self):
            return principal, 0
        def commit(self):
            assert get_ident() == self.owner
        def close(self):
            assert get_ident() == self.owner
            self.closed = True
    current = {"songs":[{"song_no":1,"level":4}],"profile":{},"dojo":{}}
    with PublicationStore(tmp_path, "111").exclusive() as store:
        store.commit({"current":json.dumps(current).encode()})
    async def scenario():
        pool = RenderExecutor(1)
        provider = TinfoHostProvider(connection_factory=Connection, userdata_root=tmp_path)
        main = get_ident()
        try:
            private = await pool.run(lambda:provider.prepare(principal,principal))
            assert connections and all(c.closed and c.owner != main for c in connections)
            provider.verify(private)
            assert connections[-1].closed and connections[-1].owner == main
            state["visible"] = 0
            with pytest.raises(TinfoDenied):
                provider.verify(private)
            with pytest.raises(TinfoDenied):
                await pool.run(lambda:provider.prepare("onebot_v11:99999",principal))
        finally:
            await pool.shutdown()
        assert all(c.closed for c in connections)
    asyncio.run(scenario())
