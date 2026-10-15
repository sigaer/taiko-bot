"""Owned public score commands and center-only authorized player estimate."""
from importlib import import_module
from nonebot import on_regex
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from . import entry

host = import_module(f'.{entry.profile()}.score_handlers', __package__)
score_line_cmd = on_regex(r"^分数线\b.*$", priority=5, rule=entry.feature_on('taiko'), block=True)
score_cmd = on_regex(r"^/?查分(?:\s*(里|表))?\s*(\S+)\s+(\d+)\s+(\d+)(?:\s+(\d+))?$", priority=5, rule=entry.feature_on('taiko'), block=True)
score_line_cmd.append_handler(host.handle_line)
score_cmd.append_handler(host.handle_score)

if entry.profile() == 'center':
    score_estimate_cmd = on_regex(r"^/?估分.*$", priority=5, rule=entry.feature_on('taiko'), block=True)

    @score_estimate_cmd.handle()
    async def handle_estimate(matcher: Matcher, event: Event):
        actor = entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
        principal, _ = entry.helpers._resolve_requested_identity_key(event)
        provider = entry.create_provider()
        try:
            private = provider.prepare(actor, principal)
        except entry.TinfoDenied as error:
            text = entry.helpers._taiko_bind_usage_message(event) if error.status == 404 else '查不到呢，可能不给看哦~'
            await entry.helpers._finish_text_reply(matcher, event, text)
            return
        except (entry.MergedBindError, entry.TinfoUnavailable) as error:
            try:
                provider.verify_initial()
                await entry.helpers._finish_text_reply(entry.AuthorizedDelivery(matcher, provider, None), event, str(error))
            except (entry.TinfoDenied, entry.TinfoUnavailable):
                await entry.helpers._finish_text_reply(matcher, event, '查不到呢，可能不给看哦~')
            return
        try:
            provider.verify(private)
            await host.execute_estimate(entry.AuthorizedDelivery(matcher, provider, private), event, private, provider)
        except (entry.TinfoDenied, entry.TinfoUnavailable):
            await entry.helpers._finish_text_reply(matcher, event, '查不到呢，可能不给看哦~')
