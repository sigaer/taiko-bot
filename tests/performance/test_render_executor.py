import asyncio
from threading import Event, Lock
import time

import pytest
from taiko_application.score.cancellation import check_cancelled
from taiko_bot.runtime.player.render_executor import RenderExecutor, RenderBusy, can_render_in_worker


def test_two_workers_one_waiter_and_event_loop_keeps_running():
    async def scenario():
        pool = RenderExecutor(2)
        release, both = Event(), Event()
        lock = Lock()
        active = maximum = started = 0
        def render():
            nonlocal active, maximum, started
            with lock:
                active += 1
                started += 1
                maximum = max(maximum, active)
                if started >= 2: both.set()
            try:
                while not release.wait(.005):check_cancelled()
                return 'image'
            finally:
                with lock:active -= 1
        tasks=[asyncio.create_task(pool.run(render)) for _ in range(3)]
        ticks=0
        while not both.is_set():
            ticks+=1
            await asyncio.sleep(.001)
        with pytest.raises(RenderBusy):await pool.run(render)
        assert len(pool._active)==2 and pool._admitted==3 and ticks>0
        release.set()
        assert await asyncio.gather(*tasks)==['image']*3
        assert maximum==2 and not pool._active and pool._admitted==0
        await pool.shutdown()
    asyncio.run(scenario())


def test_cancel_timeout_and_exception_release_capacity_after_worker_stops():
    async def scenario():
        pool=RenderExecutor(1)
        started,stopped=Event(),Event()
        def long_render():
            started.set()
            try:
                while True:
                    check_cancelled()
                    time.sleep(.002)
            finally:stopped.set()
        task=asyncio.create_task(pool.run(long_render))
        while not started.is_set():await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        if not stopped.is_set():assert pool._admitted==1
        while not stopped.is_set() or pool._admitted:await asyncio.sleep(.001)
        assert await pool.run(lambda:42)==42
        with pytest.raises(TimeoutError):await pool.run(long_render,timeout=.01)
        while pool._admitted:await asyncio.sleep(.001)
        def broken():raise ValueError('synthetic render failure')
        with pytest.raises(ValueError):await pool.run(broken)
        assert await pool.run(lambda:43)==43
        await pool.shutdown()
    asyncio.run(scenario())


def test_queued_timeout_and_repeated_start_shutdown():
    async def scenario():
        pool=RenderExecutor(1)
        for _ in range(4):
            await pool.start()
            gate=Event()
            task=asyncio.create_task(pool.run(lambda:gate.wait(.2)))
            while not pool._active:await asyncio.sleep(.001)
            with pytest.raises(TimeoutError):await pool.run(lambda:False,timeout=.005)
            assert pool._admitted==1
            gate.set();await task
            await pool.shutdown()
            assert pool._pool is None and not pool._active and not pool._admitted
    asyncio.run(scenario())


def test_matplotlib_remains_on_its_original_thread():
    assert can_render_in_worker((20,[],True,False,None))
    assert can_render_in_worker((30,[],False,False,None))
    assert can_render_in_worker((30,['精度'],False,False,'accuracy_power'))
    assert not can_render_in_worker((30,['-r'],False,True,None))
