"""Offline tasks keep the existing runtime directory unless explicitly overridden."""
import os
from pathlib import Path

def root():
    return Path(os.environ.get("TAIKO_OFFLINE_ROOT") or os.environ.get("TAIKO_CENTER_ROOT") or "/home/sigaer/taiko").resolve()
