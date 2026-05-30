from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Dict

from nonebot.adapters.onebot.reverse_ws_stats import reverse_ws_stats
from nonebot.adapters.onebot.v11.adapter import Adapter as BaseAdapter
from nonebot.adapters.onebot.v11.bot import Bot
from nonebot.adapters.onebot.v11.utils import log
from nonebot.drivers import WebSocket
from nonebot.exception import WebSocketClosed
from nonebot.utils import escape_tag

try:
    from nonebot.adapters.onebot.v11.adapter import REVERSE_WS_STATS_SOURCE
except ImportError:
    REVERSE_WS_STATS_SOURCE = "onebot.v11.reverse_ws"


class Adapter(BaseAdapter):
    """OneBot V11 reverse-WS adapter that lets newer same-self-id sessions take over."""

    def __init__(self, driver, **kwargs):
        super().__init__(driver, **kwargs)
        reverse_ws_stats.init_source(REVERSE_WS_STATS_SOURCE)
        self._handoff_locks: Dict[str, asyncio.Lock] = {}
        self._session_generations: Dict[str, int] = {}
        self._session_closed_events: Dict[str, asyncio.Event] = {}

    def _handoff_lock(self, self_id: str) -> asyncio.Lock:
        lock = self._handoff_locks.get(self_id)
        if lock is None:
            lock = asyncio.Lock()
            self._handoff_locks[self_id] = lock
        return lock

    async def _force_cleanup_existing_session(
        self,
        self_id: str,
        generation: int,
        closed_event: asyncio.Event,
    ) -> None:
        async with self._handoff_lock(self_id):
            if self._session_generations.get(self_id) != generation:
                return
            self.connections.pop(self_id, None)
            reverse_ws_stats.remove_bot(REVERSE_WS_STATS_SOURCE, self_id)
            bot = self.bots.get(self_id)
            if bot is not None:
                with contextlib.suppress(RuntimeError):
                    self.bot_disconnect(bot)
            self._session_generations.pop(self_id, None)
            if self._session_closed_events.get(self_id) is closed_event:
                self._session_closed_events.pop(self_id, None)
            closed_event.set()

    async def _handle_ws(self, websocket: WebSocket) -> None:
        self_id = websocket.request.headers.get("x-self-id")
        if not self_id:
            log("WARNING", "Missing X-Self-ID Header")
            await websocket.close(1008, "Missing X-Self-ID Header")
            return

        response = self._check_access_token(websocket.request)
        if response is not None:
            content = response.content
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            else:
                content = str(content)
            await websocket.close(1008, content)
            return

        handoff_lock = self._handoff_lock(self_id)
        session_generation = 0
        closed_event = asyncio.Event()

        while True:
            async with handoff_lock:
                old_websocket = self.connections.get(self_id)
                if old_websocket is None:
                    session_generation = self._session_generations.get(self_id, 0) + 1
                    closed_event = asyncio.Event()
                    self._session_generations[self_id] = session_generation
                    self._session_closed_events[self_id] = closed_event

                    await websocket.accept()
                    bot = Bot(self, self_id)
                    self.bot_connect(bot)
                    self.connections[self_id] = websocket
                    reverse_ws_stats.add_bot(REVERSE_WS_STATS_SOURCE, self_id)
                    log("INFO", f"<y>Bot {escape_tag(self_id)}</y> connected")
                    break

                previous_generation = self._session_generations.get(self_id, 0)
                previous_closed_event = self._session_closed_events.get(self_id)
                if previous_closed_event is None:
                    previous_closed_event = asyncio.Event()
                    self._session_closed_events[self_id] = previous_closed_event

            log("INFO", f"handoff websocket for bot <y>{escape_tag(self_id)}</y>")
            with contextlib.suppress(Exception):
                await old_websocket.close(1012, "Replaced by newer connection")

            try:
                await asyncio.wait_for(previous_closed_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                log(
                    "WARNING",
                    f"force cleanup stale websocket for bot <y>{escape_tag(self_id)}</y>",
                )
                await self._force_cleanup_existing_session(
                    self_id, previous_generation, previous_closed_event
                )

        try:
            while True:
                data = await websocket.receive()
                json_data = json.loads(data)
                if event := self.json_to_event(json_data):
                    task = asyncio.create_task(bot.handle_event(event))
                    task.add_done_callback(self.tasks.discard)
                    self.tasks.add(task)
        except WebSocketClosed:
            log("WARNING", f"WebSocket for Bot {escape_tag(self_id)} closed by peer")
        except Exception as e:
            log(
                "ERROR",
                "<r><bg #f8bbd0>Error while process data from websocket "
                f"for bot {escape_tag(self_id)}.</bg #f8bbd0></r>",
                e,
            )
        finally:
            with contextlib.suppress(Exception):
                await websocket.close()
            async with handoff_lock:
                if self._session_generations.get(self_id) == session_generation:
                    self.connections.pop(self_id, None)
                    reverse_ws_stats.remove_bot(REVERSE_WS_STATS_SOURCE, self_id)
                    current_bot = self.bots.get(self_id)
                    if current_bot is bot:
                        with contextlib.suppress(RuntimeError):
                            self.bot_disconnect(bot)
                    self._session_generations.pop(self_id, None)
                    if self._session_closed_events.get(self_id) is closed_event:
                        self._session_closed_events.pop(self_id, None)
            closed_event.set()
