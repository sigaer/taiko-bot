"""Nonsecret installed-package provenance for startup and release verification."""
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
import sys


def runtime_inventory():
    packages = {
        'taiko-bot':'taiko_bot', 'taiko-application':'taiko_application',
        'sakura-taiko-core':'sakura_taiko_core', 'sakura-taiko-contract':'sakura_taiko_contract',
        'Pillow':'PIL',
    }
    return dict(python=sys.version.split()[0],executable=sys.executable,
        packages={name:dict(version=version(name),module=str(Path(import_module(module).__file__).resolve()))
                  for name,module in packages.items()},numpy=version('numpy'),pandas=version('pandas'))
