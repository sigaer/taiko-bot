"""Cooperative cancellation for pure rendering work; no host dependencies."""
from contextvars import ContextVar

render_stop = ContextVar('taiko_render_stop', default=None)


class RenderCancelled(RuntimeError):
    pass


def check_cancelled():
    event = render_stop.get()
    if event is not None and event.is_set():
        raise RenderCancelled('Rendering cancelled')
