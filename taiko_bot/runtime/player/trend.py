"""History commands: captured private inputs, host-owned archive writes."""
import re
from importlib import import_module
from nonebot import on_message, on_regex
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from taiko_application.commands import CommandResult
from taiko_application.private_input import thaw
from . import entry

PROFILE = entry.profile()
TREND_PATTERN = r'^/?(taikotrend|rating走势)\s*(.*)$'
PLAY_PATTERN = r'^/?(taikoplaytrend|rating场次|rating游玩)\s*(.*)$'


def register(pattern):
    async def eligible(event: Event):
        return re.match(pattern, entry.helpers.extract_plain_text(event), re.I) is not None
    return (on_message(rule=entry.feature_on('taiko') & Rule(eligible)) if PROFILE == 'center'
            else on_regex(pattern, flags=re.I, rule=entry.feature_on('taiko')))


trend = register(TREND_PATTERN)
playtrend = register(PLAY_PATTERN)


def modules():
    return tuple(import_module(f'.{PROFILE}.trend_support.{name}', __package__)
                 for name in ('parsing', 'score_calculator'))


def prepare(text, play=False):
    parsing, _ = modules()
    match = re.match(PLAY_PATTERN if play else TREND_PATTERN, text, re.I)
    if not match:
        raise ValueError(parsing.PLAYTREND_USAGE_MESSAGE if play else parsing.TREND_USAGE_MESSAGE)
    argument = (match.group(2) or '').strip()
    version = 'v1'
    extra = {}
    if PROFILE == 'center':
        version, argument = parsing._extract_rating_version(argument)
        if version == 'v2':
            extra['dim_aliases'] = parsing.V2_TREND_DIM_ALIASES
    options = (parsing._parse_playtrend_args if play else parsing._parse_trend_args)(argument, **extra)
    return play, version, options, argument


def execute(private, command, points=None):
    """No provider, storage handle or writable callback crosses this boundary."""
    parsing, renderer = modules()
    play, version, options, argument = command
    user_id = private.authorized_target.user_id
    extra = {}
    if PROFILE == 'center':
        if version == 'v2':
            style = import_module('.center.trend_support.taikob_v2', __package__)
            extra = dict(trend_dim_columns=style.V2_DIM_COLUMNS,
                         trend_short_labels=style.V2_TREND_SHORT_LABELS,
                         trend_colors=style.V2_TREND_COLORS)
        render = renderer.generate_rating_playcount_image_with_status if play else renderer.generate_rating_trend_image_with_status
        status, image = render(user_id, prepared_points=points, **options, **extra)
    else:
        render = renderer.generate_rating_playcount_image if play else renderer.generate_rating_trend_image
        image = render(user_id, history_snapshots=thaw(private.history), **options)
        status = 'no_snapshot'
    if not image:
        message = ('已有历史游玩记录，但暂无鬼/里难度成绩可用于生成趋势图' if status == 'no_rating_data'
                   else '暂无历史快照，请多次使用“taikoupdate”后再试')
        if play:
            message += ('（曲线按总曲数展示，两次更新之间的多场游玩会合并为一个点）。' if status == 'no_rating_data'
                        else '（曲线按总曲数展示，两次更新之间的多场游玩会合并为一个点）')
        elif status == 'no_rating_data':
            message += '。'
        return CommandResult('text', message)
    prefix = ''
    if PROFILE == 'center' and not play and not argument:
        prefix = parsing.TREND_V2_DEFAULT_NOTE_MESSAGE if version == 'v2' else parsing.TREND_DEFAULT_NOTE_MESSAGE
    return CommandResult('image', parsing._to_jpeg_bytes(image, quality=85), prefix_text=prefix)


async def handle(matcher, event, play):
    try:
        command = prepare(entry.helpers.extract_plain_text(event), play)
    except ValueError as error:
        await matcher.finish(str(error))
        return
    actor = entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
    principal, _ = entry.helpers._resolve_requested_identity_key(event)
    provider = entry.create_provider()
    try:
        private = provider.prepare_trend(actor, principal, command)
    except entry.TinfoDenied as error:
        message = entry.helpers._taiko_bind_usage_message(event) if error.status == 404 else '查不到呢，可能不给看哦~'
        await entry.helpers._finish_text_reply(matcher, event, message)
        return
    except Exception as error:
        from .center.taikob_v2_data import V2DataSourceError
        accepted = ((entry.MergedBindError, entry.TinfoUnavailable, V2DataSourceError) if PROFILE == 'center'
                    else (entry.UserdataProviderError, entry.TinfoUnavailable))
        if not isinstance(error, accepted):
            raise
        try:
            provider.verify_initial()
            message = 'Rating v2 上游定数数据暂时不可用，请稍后再试' if isinstance(error,V2DataSourceError) else str(error)
            await entry.helpers._finish_text_reply(entry.AuthorizedDelivery(matcher,provider,None),event,message)
        except (entry.TinfoDenied, entry.TinfoUnavailable):
            await entry.helpers._finish_text_reply(matcher,event,'查不到呢，可能不给看哦~')
        return
    try:
        provider.verify(private)
        delivery = entry.AuthorizedDelivery(matcher, provider, private)
        if PROFILE == 'client':
            from taiko_bot.public_data import ensure_asset_resource_available
            from taiko_bot.settings import get_settings
            ok, message = ensure_asset_resource_available(('core-assets',), get_settings())
            if not ok:
                await entry.helpers._finish_text_reply(delivery,event,message)
                return
        result = execute(private, command, getattr(provider,'trend_points',None))
        provider.verify(private)
        await entry.deliver(delivery,event,result,rating_v2=command[1] == 'v2')
    except (entry.TinfoDenied, entry.TinfoUnavailable):
        await entry.helpers._finish_text_reply(matcher,event,'授权已失效，请重新查询。' if PROFILE=='client' else '查不到呢，可能不给看哦~')


@trend.handle()
async def trend_handle(matcher: Matcher, event: Event):
    await handle(matcher, event, False)


@playtrend.handle()
async def playtrend_handle(matcher: Matcher, event: Event):
    await handle(matcher, event, True)
