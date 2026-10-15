"""Per-actor serialization is independent of the full binding proof tests."""
import asyncio
from types import SimpleNamespace
from taiko_bot.runtime.player import lifecycle_authority as authority

def test_same_actor_serializes_and_cancelled_waiter_releases_reference(monkeypatch):
    monkeypatch.setattr(authority,'BindingGuard',lambda actor: object())
    host=SimpleNamespace(_normalize_identity_key=lambda value:value,get_identity_key=lambda event:event.actor)
    entered=asyncio.Event();release=asyncio.Event();order=[]
    @authority.manual_boundary('manual_claim_code',host)
    async def operation(event):
        order.append(event.name)
        if event.name=='first':
            entered.set();await release.wait()
    async def run():
        first=asyncio.create_task(operation(SimpleNamespace(actor='same',name='first')))
        await entered.wait()
        cancelled=asyncio.create_task(operation(SimpleNamespace(actor='same',name='cancelled')))
        second=asyncio.create_task(operation(SimpleNamespace(actor='same',name='second')))
        await asyncio.sleep(0)
        assert order==['first']
        cancelled.cancel()
        try:await cancelled
        except asyncio.CancelledError:pass
        # A different actor remains independent while the first actor waits.
        await operation(SimpleNamespace(actor='other',name='other'))
        assert order==['first','other']
        release.set();await asyncio.gather(first,second)
    asyncio.run(run())
    assert order==['first','other','second']
    assert not authority._locks
