"""Private bounded cache helpers; no account state or calculation changes."""
import os
import sys

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
