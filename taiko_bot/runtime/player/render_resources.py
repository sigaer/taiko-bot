"""Request resource scope for function-based profile renderers."""
from contextvars import ContextVar
from functools import wraps
from taiko_application.score.static_resources import RequestResources

_current = ContextVar('taiko_render_resources', default=None)


def resources():
    return _current.get()


def request_resources(function):
    @wraps(function)
    def render(*args, **kwargs):
        if resources() is not None:
            return function(*args, **kwargs)
        scope = RequestResources()
        token = _current.set(scope)
        try:
            result = function(*args, **kwargs)
            scope.release(result)
            return result
        finally:
            _current.reset(token)
            scope.close()
    return render
