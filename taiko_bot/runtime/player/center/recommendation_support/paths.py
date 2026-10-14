"""Public resources for the native host; no private data access."""
import os
from pathlib import Path

ROOT = Path(os.getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko"))
