"""Two render workers, no submitted backlog, cooperative timeout/cancellation.

Only captured calculation/rendering closures belong here. Providers, leases,
SQL sessions and transport operations stay on their owning event loop.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from taiko_application.score.cancellation import render_stop, check_cancelled


class RenderBusy(RuntimeError):
    pass


class RenderExecutor:
    def __init__(self, workers=2):
        if workers not in (1, 2):
            raise ValueError('Render worker budget must be one or two')
        self.workers = workers
        self._pool = None
        self._slots = None
        self._active = {}
        self._closing = False
        self._admitted = 0

    async def start(self):
        if self._pool is None:
            self._closing = False
            self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix='taiko-render')
            self._slots = asyncio.Semaphore(self.workers)

    async def _reserve(self, timeout):
        if self._closing:
            raise RuntimeError('Render executor is shutting down')
        await self.start()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        if self._admitted >= self.workers + 1:
            raise RenderBusy('Render queue is full')
        self._admitted += 1
        slots = self._slots
        try:
            await asyncio.wait_for(slots.acquire(), timeout)
        except BaseException:
            self._admitted -= 1
            raise
        if self._closing:
            slots.release()
            self._admitted -= 1
            raise RuntimeError('Render executor is shutting down')
        return slots, deadline

    async def run(self, function, *, timeout=60):
        slots, deadline = await self._reserve(timeout)
        loop = asyncio.get_running_loop()
        stop = Event()
        def work():
            token = render_stop.set(stop)
            try:
                check_cancelled()
                return function()
            finally:
                render_stop.reset(token)
        try:
            future = loop.run_in_executor(self._pool, work)
        except BaseException:
            slots.release()
            self._admitted -= 1
            raise
        self._active[future] = stop
        def finished(done):
            self._active.pop(done, None)
            slots.release()
            self._admitted -= 1
            if not done.cancelled():
                done.exception()  # Also consume errors from timed-out/cancelled callers.
        future.add_done_callback(finished)
        try:
            return await asyncio.wait_for(asyncio.shield(future), max(0, deadline-loop.time()))
        except (asyncio.CancelledError, TimeoutError):
            stop.set()
            raise

    async def run_on_host(self, function, *, timeout=60):
        # pyplot stays on the host thread, but consumes the same render budget.
        slots, _ = await self._reserve(timeout)
        try:
            return function()
        finally:
            slots.release()
            self._admitted -= 1

    async def shutdown(self):
        self._closing = True
        if self._pool is None:
            return
        active = tuple(self._active)
        for stop in self._active.values():
            stop.set()
        pool = self._pool
        pool.shutdown(wait=False, cancel_futures=True)
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        # All work has completed; join only the workers exiting their sentinels.
        pool.shutdown(wait=True, cancel_futures=True)
        self._pool = self._slots = None


executor = RenderExecutor()


def can_render_in_worker(command):
    _, args, use_v2, _, dim = command
    # pyplot remains on its existing host thread; Pillow-only branches are pure.
    return use_v2 or not args or dim is not None
