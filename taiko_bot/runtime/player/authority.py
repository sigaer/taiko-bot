"""Request-scoped delivery authorization, shared by the two hosts."""
from nonebot.exception import FinishedException
class TinfoDenied(Exception):
    def __init__(self, status=403):
        self.status = status
        super().__init__("查不到呢，可能不给看哦~")


class TinfoUnavailable(Exception):
    def __init__(self):
        super().__init__("成绩暂不可用，请稍后重试。")


class AuthorizedDelivery:
    """Private player transport facade; recheck every send and passive-failure fallback."""
    def __init__(self, matcher, provider, prepared):
        self._matcher, self._provider, self._prepared = matcher, provider, prepared

    def __getattr__(self, name):
        return getattr(self._matcher, name)

    def _verify(self):
        if self._prepared is None:
            self._provider.verify_initial()
        else:
            self._provider.verify(self._prepared)

    async def send(self, *args, **kwargs):
        self._verify()
        try:
            return await self._matcher.send(*args, **kwargs)
        except Exception:
            # The shared QQ adapter may next attempt proactive delivery. This
            # check runs after the failed network await, before that fallback.
            self._verify()
            raise

    async def finish(self, *args, **kwargs):
        if args or kwargs:
            self._verify()
        try:
            return await self._matcher.finish(*args, **kwargs)
        except FinishedException:
            raise  # Normal successful matcher completion, not a send failure.
        except Exception:
            if args or kwargs:
                self._verify()
            raise
