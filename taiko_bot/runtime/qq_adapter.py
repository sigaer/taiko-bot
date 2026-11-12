"""Keep QQ transport unchanged and timestamp dispatch before task scheduling."""
from nonebot.adapters.qq import Adapter as BaseAdapter
from .request_timing import event_dispatch


class Adapter(BaseAdapter):
    def dispatch_event(self, bot, payload):
        with event_dispatch("qq_adapter_dispatch"):
            return super().dispatch_event(bot, payload)
