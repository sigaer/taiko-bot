"""Bounded B30 latency spans. Never retain event, authority or API payloads.

Spans are inclusive intervals on one monotonic clock. They may be nested and
must not be added together. Only the trace's numeric timing data crosses into
the render worker; its ContextVars and authority objects do not.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from importlib.metadata import PackageNotFoundError, version
import json
from threading import Lock
from time import perf_counter_ns
from uuid import uuid4


_ingress = ContextVar("taiko_event_ingress", default=None)
_current = ContextVar("taiko_b30_timing", default=None)
_installed = False
MAX_SPANS = 128
UPLOAD_APIS = frozenset(("post_group_files", "post_c2c_files", "post_group_upload_prepare",
                         "post_c2c_upload_prepare", "put_upload_part",
                         "post_group_upload_part_finish", "post_c2c_upload_part_finish"))
SEND_APIS = frozenset(("post_group_messages", "post_c2c_messages", "post_messages",
                       "post_dms_messages", "send_msg", "send_group_msg", "send_private_msg"))


@contextmanager
def event_dispatch(source):
    """Capture before the adapter creates its event task; reset the parent."""
    token = _ingress.set((perf_counter_ns(), source))
    try:
        yield
    finally:
        _ingress.reset(token)


def _outcome(error):
    if error is None or type(error).__name__ == "FinishedException":
        return "completed"
    return "cancelled" if type(error).__name__ == "CancelledError" else "error"


def _emit(row):
    from nonebot.log import logger
    logger.info("Taiko B30 timing: {}", json.dumps(row, separators=(",", ":")))


class RequestTrace:
    def __init__(self, *, platform, profile, emit=_emit, clock=perf_counter_ns):
        self.clock, self.emit = clock, emit
        self.handler_started = clock()
        ingress = _ingress.get()
        self.started, self.boundary = ingress or (self.handler_started, "b30_handler")
        self.request_id = uuid4().hex[:16]
        self.platform = platform if platform in ("qq_official", "onebot_v11") else "other"
        self.profile = "center" if profile == "center" else "client"
        self.command = {}
        self.spans, self.pending = [], {}
        self.dropped = 0
        self.send_ack = None
        self.lock = Lock()

    def select(self, command):
        n, _, use_v2, dynamic, dimension = command
        self.command = dict(top_n=n if type(n) is int and 1 <= n <= 50 else None,
                            rating="v2" if use_v2 else "v1", dynamic=bool(dynamic),
                            dimension=dimension if dimension in {
                                "accuracy_power", "stamina_power", "speed_power",
                                "reading_power", "rhythm_power", "technique_power"} else None)

    def record(self, name, started, ended, status="completed"):
        with self.lock:
            if len(self.spans) >= MAX_SPANS:
                self.dropped += 1
                return
            self.spans.append(dict(name=name, start_ms=round((started-self.started)/1e6, 3),
                                   duration_ms=round((ended-started)/1e6, 3), status=status))

    @contextmanager
    def phase(self, name):
        started, error = self.clock(), None
        try:
            yield
        except BaseException as exc:
            error = exc
            raise
        finally:
            self.record(name, started, self.clock(), _outcome(error))

    def api_begin(self, api, data):
        if api not in UPLOAD_APIS | SEND_APIS:
            return
        with self.lock:
            if len(self.pending) < 16:
                self.pending[(api, id(data))] = self.clock()

    def api_end(self, api, data, error):
        ended = self.clock()
        with self.lock:
            started = self.pending.pop((api, id(data)), None)
            if started is not None and api in SEND_APIS and error is None:
                self.send_ack = max(self.send_ack or ended, ended)
        if started is not None:
            self.record("api."+api, started, ended, _outcome(error))

    @contextmanager
    def activate(self):
        # Set this numeric trace only; never copy the caller's whole Context.
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)

    @contextmanager
    def scope(self):
        error = None
        try:
            with self.activate():
                yield self
        except BaseException as exc:
            error = exc
            raise
        finally:
            self.finish(error)

    def finish(self, error=None):
        ended = self.clock()
        try:
            release = version("taiko-bot")
        except PackageNotFoundError:
            release = "source"
        with self.lock:
            row = dict(schema=1, request_id=self.request_id, release=release,
                       platform=self.platform, profile=self.profile, boundary=self.boundary,
                       command=self.command, status=_outcome(error),
                       dispatch_to_handler_ms=round((self.handler_started-self.started)/1e6, 3),
                       handler_total_ms=round((ended-self.handler_started)/1e6, 3),
                       dispatch_to_finish_ms=round((ended-self.started)/1e6, 3),
                       dispatch_to_send_ack_ms=round((self.send_ack-self.started)/1e6, 3) if self.send_ack else None,
                       spans=sorted(self.spans, key=lambda span: span["start_ms"]),
                       dropped_spans=self.dropped, unfinished_api_calls=len(self.pending))
            self.pending.clear()
        try:
            self.emit(row)
        except Exception:
            pass  # Observability failure must not change a reply or its error.


@contextmanager
def phase(name):
    trace = _current.get()
    if trace is None:
        yield
    else:
        with trace.phase(name):
            yield


def measured(name):
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            with phase(name):
                return function(*args, **kwargs)
        return call
    return decorate


async def _api_calling(bot, api, data):
    if (trace := _current.get()) is not None:
        trace.api_begin(api, data)


async def _api_called(bot, exception, api, data, result):
    if (trace := _current.get()) is not None:
        trace.api_end(api, data, exception)


def install_api_hooks():
    global _installed
    if not _installed:
        from nonebot.adapters import Bot
        Bot.on_calling_api(_api_calling)
        Bot.on_called_api(_api_called)
        _installed = True
