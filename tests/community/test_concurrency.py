import asyncio
from taiko_bot.runtime.community.concurrency import serialized, _pending


def test_cancelled_waiter_and_failed_owner_release_all_keys():
    async def scenario():
        entered=asyncio.Event(); release=asyncio.Event(); order=[]
        async def owner():
            async with serialized(('draw','group')):
                entered.set();await release.wait();raise ValueError('synthetic')
        async def waiter():
            async with serialized(('draw','group')):order.append('waiter')
        first=asyncio.create_task(owner());await entered.wait()
        waiting=asyncio.create_task(waiter());await asyncio.sleep(0)
        waiting.cancel()
        try:await waiting
        except asyncio.CancelledError:pass
        # Unrelated groups never wait for this group's network IO.
        async with serialized(('draw','other')):order.append('other')
        release.set()
        try:await first
        except ValueError:pass
        assert order==['other'] and not _pending
        async with serialized(('draw','group')):pass
        assert not _pending
    asyncio.run(scenario())


def test_oss_interface_keeps_command_and_failure_details(monkeypatch,tmp_path):
    import nonebot
    from importlib import import_module
    from taiko_bot.runtime.public.config import profile
    nonebot.require('taiko_bot.runtime.community.community_entry')
    module=import_module(f'taiko_bot.runtime.community.{profile()}.cover')
    path=tmp_path/'1.png';path.write_bytes(b'synthetic')
    calls=[]
    def run(command,**kwargs):calls.append((command,kwargs))
    monkeypatch.setattr(module.subprocess,'run',run)
    assert module._upload_cover_to_oss(path)==(True,'oss://sigaer/cover/1.png')
    assert calls==[(['ossutil','cp','-f',str(path),'oss://sigaer/cover/1.png'],{'check':True,'capture_output':True,'text':True})]
    def fail(*args,**kwargs):raise RuntimeError('synthetic OSS refused')
    monkeypatch.setattr(module.subprocess,'run',fail)
    assert module._upload_cover_to_oss(path)==(False,'synthetic OSS refused')
