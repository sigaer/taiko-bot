"""Recommendation entry in the existing player plugin, for both host profiles."""
import re
from importlib import import_module
from types import SimpleNamespace

from nonebot import on_regex, logger
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from taiko_application.commands import CommandContext, CommandResult
from taiko_application.commands.recommendation import (
    PreparedRecommendationCommand, execute_recommendation, prepare_recommendation,
)
from taiko_application.private_input import thaw
from . import entry

PROFILE = entry.profile()
ALIASES = 'taikorec|推荐歌曲|歌曲推荐' if PROFILE == 'center' else 'taikorec|推荐歌曲'
taikorec = on_regex(rf'^(?:{ALIASES}).*$', flags=re.IGNORECASE,
                    rule=entry.feature_on('taiko'))


def support():
    return import_module(f'.{PROFILE}.recommendation_support.score_calculator', __package__)


def parse(text):
    aliases = import_module(f'.{PROFILE}.recommendation_support.aliases', __package__)
    # Target parsing is Core-owned, matching the frozen host profile.
    target = import_module('sakura_taiko_core.recommendation.' + PROFILE)
    ports = SimpleNamespace(DIM_MAP=aliases.DIM_MAP,
        TAIKOREC_COMMAND_EXTRACT_RE=re.compile(rf'^(?:{ALIASES})\s*(.*)$', re.IGNORECASE),
        parse_target_recommendation_request=target.parse_target_recommendation_request,
        target_recommendation_displays=target.target_recommendation_displays)
    return prepare_recommendation(CommandContext(text=text, profile=PROFILE), ports)


def prepare_result(request, private, provider):
    """All calculation/presentation acquisition happens in the host, before execute."""
    if isinstance(request, CommandResult):
        return PreparedRecommendationCommand(request)
    current = thaw(private.current)
    module = support()
    try:
        if private.current_failure:
            error = private.current_failure
            raise (FileNotFoundError(error.message) if error.missing else ValueError(error.message))
        if request.target_key:
            target = import_module(f'.{PROFILE}.recommendation_support.target_recommend', __package__)
            result = target.compute_target_recommendations_from_userdata(current, request.target_key,
                                                                          star_filter=request.star_filter)
        else:
            rows = module.compute_recommendations_from_records(current['songs'],
                best_key=request.basis, limit=request.limit)
    except FileNotFoundError:
        hint = getattr(provider, 'recommendation_missing_hint', '您还未上传数据哦~请先发送“taikoupdate”进行上传')
        return PreparedRecommendationCommand(request, failure='missing', missing_hint=hint)
    except Exception as error:
        logger.warning("Recommendation calculation failed: {}", type(error).__name__)
        return PreparedRecommendationCommand(request, failure='calculation')
    if request.target_key:
        if not result.is_enough:
            return PreparedRecommendationCommand(request, target_message=result.message)
        renderer = import_module(f'.{PROFILE}.recommendation_support.target_render', __package__)
        image = renderer.render_target_recommendation_image_bytes(
            user_id=private.authorized_target.user_id, userdata=current,
            target_display=result.target_display, rows=result.rows,
            font_path='assets/fonts/DDFont.ttf')
    else:
        kwargs = dict(title='以下是可供参考的推荐歌曲',
                      subtitle=f'维度：{request.dimension}  数量：{request.limit}',
                      font_path='assets/fonts/DDFont.ttf')
        if PROFILE == 'center':
            kwargs.update(userdata=current, user_id=private.authorized_target.user_id)
        image = module.generate_recommend_image(rows, **kwargs)
    if hasattr(image, 'getvalue'):
        image = image.getvalue()
    return PreparedRecommendationCommand(request, image=image)


@taikorec.handle()
async def taikorec_handle(matcher: Matcher, event: Event):
    actor = entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
    principal, _ = entry.helpers._resolve_requested_identity_key(event)
    provider = entry.create_provider()
    try:
        private = provider.prepare(actor, principal)
    except entry.TinfoDenied as error:
        if error.status == 404:
            await entry.helpers._finish_text_reply(matcher, event, entry.helpers._taiko_bind_usage_message(event))
        await entry.helpers._finish_text_reply(matcher, event, '查不到呢，可能不给看哦~')
    except Exception as error:
        accepted = (entry.MergedBindError, entry.TinfoUnavailable) if PROFILE == 'center' else (entry.UserdataProviderError, entry.TinfoUnavailable)
        if not isinstance(error, accepted):
            raise
        try:
            provider.verify_initial()
            await entry.helpers._finish_text_reply(entry.AuthorizedDelivery(matcher, provider, None), event, str(error))
        except (entry.TinfoDenied, entry.TinfoUnavailable):
            await entry.helpers._finish_text_reply(matcher, event, '查不到呢，可能不给看哦~')
    try:
        provider.verify(private)
        delivery = entry.AuthorizedDelivery(matcher, provider, private)
        if PROFILE == 'client':
            from taiko_bot.public_data import ensure_asset_resource_available
            from taiko_bot.settings import get_settings
            ok, message = ensure_asset_resource_available(('core-assets',), get_settings())
            if not ok:
                await entry.helpers._finish_text_reply(delivery, event, message)
        request = parse(entry.helpers.extract_plain_text(event))
        prepared = prepare_result(request, private, provider)
        result = execute_recommendation(prepared)
        provider.verify(private)
        await entry.deliver(delivery, event, result)
    except (entry.TinfoDenied, entry.TinfoUnavailable):
        await entry.helpers._finish_text_reply(matcher, event, '授权已失效，请重新查询。' if PROFILE == 'client' else '查不到呢，可能不给看哦~')
