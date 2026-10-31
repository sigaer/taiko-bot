"""Small, shared resident-memory tools; standard library only."""
from .cache import BoundedLRU, estimated_size, image_bytes, font_bytes, bounded_memoize
from .metrics import register_cache, start_telemetry
from .store import LastGoodJSON, SQLiteRows
