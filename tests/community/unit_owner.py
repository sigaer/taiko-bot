"""Test-only routing for historical helper assertions after owner migration.
Production never imports this facade. Event tests exercise wrapped dispatch.
"""
import inspect
from importlib import import_module


class UnitOwner:
    def __init__(self, profile):
        modules = [import_module(f'taiko_bot.runtime.player.{profile}.{name}')
                   for name in ('lifecycle_host', 'identity_cluster', 'manual_cluster', 'update_cluster')]
        modules += [import_module(f'taiko_bot.runtime.community.{profile}.compat')]
        object.__setattr__(self, 'modules', modules)

    def __getattr__(self, name):
        for module in self.modules:
            if hasattr(module, name):
                value = getattr(module, name)
                return inspect.unwrap(value) if inspect.isfunction(value) else value
        raise AttributeError(name)

    def __setattr__(self, name, value):
        for module in self.modules:
            if hasattr(module, name):
                setattr(module, name, value)

    def __delattr__(self, name):
        for module in self.modules:
            if hasattr(module, name):
                delattr(module, name)
