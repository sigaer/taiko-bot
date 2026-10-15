"""Personal displays consume authorized values; SQL stays in the Host."""
import re
from importlib import import_module
from nonebot import on_fullmatch, on_message, on_regex
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from taiko_application.private_input import thaw
from . import entry

PROFILE = entry.profile()

async def don_eligible(event: Event):
    return entry.helpers.extract_plain_text(event).strip() == '我的小咚'

my_don = (on_message(rule=entry.feature_on('taiko') & Rule(don_eligible)) if PROFILE=='center'
          else on_fullmatch('我的小咚',rule=entry.feature_on('taiko')))


class MetricImageError(Exception):
    """Keep the legacy uncaught list/composition failure boundary."""


def render(private, options, error=None, *, kind="my_don", text=""):
    metric = import_module(f".{PROFILE}.display_support.metric", __package__)
    if private.current_failure:
        if private.current_failure.missing:
            raise FileNotFoundError('userdata not found')
        raise ValueError(private.current_failure.message)
    if error is not None:
        raise error
    module = import_module(f'.{PROFILE}.display_support.draw_dress', __package__)
    userdata = thaw(private.current)
    if kind in ('my_don', 'tcloud'):
        image = module.render_my_don_image(private.authorized_target.user_id, userdata=userdata, **options)
        if kind == 'my_don':
            return image
    if kind == 'tcloud':
        cloud = import_module(f'.{PROFILE}.display_support.tcloud', __package__)
        return cloud.render_tcloud_image(userdata, my_don_img=image)
    match = re.match(metric.SONG_METRIC_QUERY_PATTERN, text, re.I)
    if not match:
        raise ValueError('invalid metric command')
    if match.group('ng') is not None:
        mode='ng'; value=int(match.group('ng')); label=f'{value}不可'
    elif match.group('ok') is not None:
        mode='ok'; value=int(match.group('ok')); label=f'{value}可'
    elif match.group('single_ok') is not None:
        mode='single_ok'; value=None; label='单可'
    else:
        mode='dondaful'; value=None; label='全良'
    records=userdata.get('songs')
    records=[row for row in records if isinstance(row,dict)] if isinstance(records,list) else []
    matched=metric._collect_song_metric_matches(records,mode,value,metric._parse_song_metric_order(match.group('order')))
    image = module.render_my_don_image(private.authorized_target.user_id, userdata=userdata, **options)
    try:
        listing=metric._render_song_metric_list_image(label,matched[:metric.SONG_METRIC_MAX_SHOW],len(matched))
        return metric._compose_song_metric_result_image(image,listing)
    except Exception as error:
        raise MetricImageError() from error


async def handle(matcher,event,kind="my_don"):
    if kind=="tcloud" and external_bot(event):return
    actor=entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
    principal,_=entry.helpers._resolve_requested_identity_key(event)
    provider=entry.create_provider()
    try:
        private=provider.prepare_display(actor,principal)
    except entry.TinfoDenied as error:
        message=entry.helpers._taiko_bind_usage_message(event) if error.status==404 else '查不到呢，可能不给看哦~'
        if kind=='tcloud':await matcher.finish(message,reply_message=True)
        else:await entry.helpers._finish_text_reply(matcher,event,message)
        return
    except Exception as error:
        accepted=(entry.MergedBindError,entry.TinfoUnavailable) if PROFILE=='center' else (entry.UserdataProviderError,entry.TinfoUnavailable)
        if not isinstance(error,accepted):raise
        try:
            provider.verify_initial()
            message=('查询失败了，请稍后再试~' if kind=='song_metric_query' else '生成失败了，请稍后再试~') if PROFILE=='client' and isinstance(error,entry.UserdataProviderError) else str(error)
            await entry.helpers._finish_text_reply(entry.AuthorizedDelivery(matcher,provider,None),event,message)
        except (entry.TinfoDenied,entry.TinfoUnavailable):
            await entry.helpers._finish_text_reply(matcher,event,'查不到呢，可能不给看哦~')
        return
    try:
        provider.verify(private)
        delivery=entry.AuthorizedDelivery(matcher,provider,private)
        if PROFILE=='client':
            from taiko_bot.public_data import ensure_asset_resource_available
            from taiko_bot.settings import get_settings
            ok,message=ensure_asset_resource_available(('core-assets','dress-assets','nameplate-assets'),get_settings())
            if not ok:
                await entry.helpers._finish_text_reply(delivery,event,message)
                return
        try:
            image=render(private,dict(getattr(provider,'display_options',{})),getattr(provider,'display_error',None),kind=kind,text=entry.helpers.extract_plain_text(event))
        except MetricImageError as error:
            raise error.__cause__
        except FileNotFoundError:
            await entry.helpers._finish_text_reply(delivery,event,'请更新数据后使用~' if kind=='my_don' else '您还未上传数据哦~请先发送“taikoupdate”进行上传')
            return
        except Exception as error:
            message=('没有可用于生成词云的游玩数据~' if kind=='tcloud' and isinstance(error,ValueError) else '查询失败了，请稍后再试~' if kind=='song_metric_query' else '生成失败了，请稍后再试~')
            await entry.helpers._finish_text_reply(delivery,event,message)
            return
        provider.verify(private)
        await entry.helpers._finish_image_reply(delivery,event,image,**(dict(prefer_markdown_image=True,markdown_image_name='tcloud') if kind=='tcloud' else {}))
    except (entry.TinfoDenied,entry.TinfoUnavailable):
        await entry.helpers._finish_text_reply(matcher,event,'授权已失效，请重新查询。' if PROFILE=='client' else '查不到呢，可能不给看哦~')


@my_don.handle()
async def my_don_handle(matcher: Matcher,event: Event):
    await handle(matcher,event)


def external_bot(event):
    if entry.helpers.is_qq_official_event(event):return False
    return any(seg.type=='at' and seg.data.get('qq')=='3889003795' for seg in event.get_message())


async def cloud_eligible(event: Event):
    if external_bot(event):return False
    text=entry.helpers.extract_plain_text(event).strip()
    if text.startswith('/'):text=text[1:].lstrip()
    return re.fullmatch(r'(?:tcloud|太鼓词云|词云)\s*',text,re.I) is not None


# Parsing constants are public-only and import no player data providers.
_metric=import_module(f'.{PROFILE}.display_support.metric',__package__)
song_metric_query=on_regex(_metric.SONG_METRIC_QUERY_PATTERN,flags=re.I,rule=entry.feature_on('taiko'))
tcloud=on_message(rule=entry.feature_on('taiko') & Rule(cloud_eligible),block=False)


@song_metric_query.handle()
async def song_metric_query_handle(matcher: Matcher,event: Event):
    await handle(matcher,event,'song_metric_query')


@tcloud.handle()
async def tcloud_handle(matcher: Matcher,event: Event):
    await handle(matcher,event,'tcloud')
