"""Taiko-owned player matchers in the host's existing NoneBot driver."""
import os
import re
from pathlib import Path
from nonebot import on_message, on_regex, require
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from taiko_application.commands import execute_score
from taiko_application.commands.prepared_score import PreparedScoreCommand, ScoreSelection, select_score
from taiko_application.private_input import ReadFailure, thaw
from taiko_application.merged_bind import MergedBindError
# Declare the dependency before importing its registering package.
# NoneBot must own the nine public matchers even when player loads first.
require('taiko_bot.runtime.public')
from ..public.config import profile
from ..public.provider import query_with_mode, rejected_fuzzy

from importlib.metadata import version
for package, expected in [('sakura-taiko-core', '0.1.1' if profile() == 'center' else '0.1.2'), ('sakura-taiko-contract','0.1.0')]:
    if version(package) != expected:
        raise RuntimeError(f'{package} requires {expected} for {profile()}')

require('feature_handler')
from feature_handler.feature_handler import feature_on

if profile() == 'center':
    from .center import helpers, presentation
    from .center.tinfo_provider import TinfoHostProvider, TinfoDenied, TinfoUnavailable, AuthorizedDelivery
    from .center.taiko_db import get_taiko_db_connection
else:
    from .client import helpers, presentation
    from .client.provider import TinfoHostProvider, TinfoDenied, TinfoUnavailable, AuthorizedDelivery, UserdataProviderError

PATTERN = re.compile(r'^/?tinfo\s?(.+)$')

async def eligible(event: Event):
    return PATTERN.match(helpers.extract_plain_text(event).strip()) is not None

music_info = (on_message(rule=feature_on('taiko') & Rule(eligible)) if profile() == 'center'
              else on_regex(PATTERN.pattern, rule=feature_on('taiko')))


def create_provider():
    if profile() == 'center':
        return TinfoHostProvider(connection_factory=get_taiko_db_connection,
            userdata_root=os.getenv('TAIKO_USERDATA_DIR') or Path(os.getenv('TAIKO_CENTER_ROOT', '/home/sigaer/taiko'))/'userdata')
    return TinfoHostProvider()


async def deliver(matcher, event, result):
    if result.kind == 'text':
        if result.delivery == 'direct':
            await matcher.finish(result.payload)
        await helpers._finish_text_reply(matcher, event, result.payload)
    else:
        await helpers._finish_image_reply(matcher, event, result.payload, prefix_text=result.prefix_text)


@music_info.handle()
async def music_info_handle(matcher: Matcher, event: Event):
    actor = helpers._normalize_identity_key(helpers.get_identity_key(event=event))
    principal, _ = helpers._resolve_requested_identity_key(event)
    provider = create_provider()
    try:
        prepared = provider.prepare(actor, principal)
    except TinfoDenied as error:
        if error.status == 404:
            await helpers._finish_text_reply(matcher, event, helpers._taiko_bind_usage_message(event))
        await matcher.finish('查不到呢，可能不给看哦~')
    except Exception as error:
        accepted = (MergedBindError, TinfoUnavailable) if profile() == 'center' else (UserdataProviderError, TinfoUnavailable)
        if not isinstance(error, accepted):
            raise
        try:
            provider.verify_initial()
            await helpers._finish_text_reply(AuthorizedDelivery(matcher, provider, None), event, str(error))
        except (TinfoDenied, TinfoUnavailable):
            await matcher.finish('查不到呢，可能不给看哦~')
    try:
        provider.verify(prepared)
        if profile() == 'client':
            from taiko_bot.public_data import ensure_asset_resource_available
            from taiko_bot.settings import get_settings
            ok, message = ensure_asset_resource_available(('core-assets', 'cover-assets'), get_settings())
            if not ok:
                await helpers._finish_text_reply(AuthorizedDelivery(matcher, provider, prepared), event, message)
        match = PATTERN.match(helpers.extract_plain_text(event).strip())
        rows = query_with_mode(match.group(1))[0] if match else []
        fuzzy = bool(rows) and rejected_fuzzy(rows)
        selection = select_score(bool(match), rows, fuzzy=fuzzy,
            fuzzy_hint=helpers._build_fuzzy_query_hint(rows) if fuzzy else '')
        context = failure = png = None
        if isinstance(selection, ScoreSelection) and prepared.current_failure is None:
            try:
                if profile() == 'center':
                    context = presentation.prepare_score_presentation(selection.song_no, thaw(prepared.current), prefer_best_in_group=True)
                else:
                    png = presentation.generate_score_image(selection.song_no, thaw(prepared.current))
            except Exception as error:
                failure = ReadFailure(isinstance(error, FileNotFoundError), str(error))
        result = execute_score(PreparedScoreCommand(prepared, selection, context, failure, png))
        provider.verify(prepared)
        await deliver(AuthorizedDelivery(matcher, provider, prepared), event, result)
    except (TinfoDenied, TinfoUnavailable):
        await matcher.finish('查不到呢，可能不给看哦~')

# Register additional player commands in this same plugin/driver.
from . import recommendation

from . import progress

from . import b30
from . import trend  # noqa: E402,F401
