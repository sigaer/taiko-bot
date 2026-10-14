"""Private bounded cache helpers; no account state or calculation changes."""
import os
import sys

_ROOT = os.getenv("PYTHON_MEMORY_RUNTIME_ROOT", "/opt/python-memory-runtime/1.1.0")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from runtime_memory import bounded_memoize, estimated_size


def budget(name, default):
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


def rating_result_bytes(value):
    # Chart keys reference the existing source snapshot. Count the result's
    # scalar fields rather than retaining a second chart or serialized JSON.
    return estimated_size(vars(value), max_nodes=128)
