"""Capture only the complete pre-update score under the caller's Source lease."""
from taiko_store import PublicationError


def capture_previous_userdata(store):
    store._require_lock(write=True)
    view = store.reader()
    try:
        previous = view.decoded()
    except FileNotFoundError:
        if view.manifest is not None and "current" in view.manifest["files"]:
            raise PublicationError("Committed previous score is unavailable") from None
        return None
    except (ValueError, UnicodeError):
        if view.manifest is not None:
            raise PublicationError("Committed previous score is invalid") from None
        return None  # The legacy writer permits a fresh full baseline here.
    return previous if isinstance(previous, dict) else None
