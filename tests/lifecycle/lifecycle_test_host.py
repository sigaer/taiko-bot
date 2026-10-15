"""Unit-test routing for historical helper tests; real guards are tested by events.py."""
import inspect
from importlib import import_module
class UnitHost:
 def __init__(self):
  object.__setattr__(self,'modules',[import_module('taiko_bot.runtime.player.center.'+name) for name in ('lifecycle_host','identity_cluster','manual_cluster','update_cluster')])
 def __getattr__(self,name):
  for module in self.modules:
   if hasattr(module,name):
    value=getattr(module,name)
    return inspect.unwrap(value) if inspect.isfunction(value) else value
  raise AttributeError(name)
 def __setattr__(self,name,value):
  for module in self.modules:
   if hasattr(module,name):setattr(module,name,value)
 def __delattr__(self,name):
  for module in self.modules:
   if hasattr(module,name):delattr(module,name)
def host():return UnitHost()
