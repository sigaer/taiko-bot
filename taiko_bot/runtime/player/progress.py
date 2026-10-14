"""Progress entry for the existing player plugin, using captured private inputs."""
import re
from functools import partial
from importlib import import_module
from nonebot import on_message, on_regex
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from taiko_application.commands import CommandContext, CommandResult
from taiko_application.commands.progress import ProgressPorts, prepare_progress, execute_progress
from taiko_application.private_input import thaw
from . import entry

PROFILE = entry.profile()
PROGRESS_WITH_PAGE_REGEX = re.compile(r'^(?P<body>.+进度)(?:\s+(?P<page>\d+))?$')
STAR_PROGRESS_REGEX = re.compile(r'^(?P<star>10|[1-9]|一|二|两|三|四|五|六|七|八|九|十)(?:星|★|☆)进度$')
STAR_PROGRESS_VALUE_MAP = dict(zip('一二两三四五六七八九十', (1,2,2,3,4,5,6,7,8,9,10)))
FOREIGN_PROGRESS_COMMANDS = frozenset(('任务进度','账单进度','pjsk进度','twpjsk进度','cnpjsk进度','活动进度'))


def extract_match(event):
    text = entry.helpers.extract_plain_text(event).strip()
    return PROGRESS_WITH_PAGE_REGEX.fullmatch(text)


async def eligible(event: Event):
    match = extract_match(event)
    return bool(match and match['body'].strip().casefold() not in FOREIGN_PROGRESS_COMMANDS)


matcher = (on_message(rule=entry.feature_on('taiko') & Rule(eligible)) if PROFILE == 'center'
           else on_regex(r'^.+进度(?:\s+\d+)?$', rule=entry.feature_on('taiko') & Rule(eligible)))


def modules():
    base = f'.{PROFILE}.progress_support'
    return tuple(import_module(base + '.' + name, __package__) for name in ('render','dani_progress','progress_catalog'))


def build_ports(current, history, render, dani, catalog, failure=None):
    # Public catalogs and request parsing belong to Host preparation. Renderers
    # receive only captured current/history, including the captured dress profile.
    import json
    def names():
        path = render.BASE / 'songs/music_donda_list.json'
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            return set(value) if isinstance(value, dict) else set()
        except Exception:
            return set()
    def captured_render(function, **kwargs):
        if failure is not None and not failure.missing:
            raise ValueError(failure.message)
        return function(userdata=current, **kwargs)
    return ProgressPorts(STAR_PROGRESS_REGEX=STAR_PROGRESS_REGEX,
        _load_decimal_progress_set=catalog.available_const_progress_keys,
        _load_pass_progress_set=catalog.available_pass_progress_keys,
        _load_progress_name_set=names,
        _load_star_progress_set=catalog.available_star_progress_values,
        _parse_star_progress_value=lambda raw: int(raw) if raw.isdigit() else STAR_PROGRESS_VALUE_MAP.get(raw),
        parse_dani_progress_request=dani.parse_dani_progress_request,
        render_dani_progress_image_bytes=partial(captured_render,dani.render_dani_progress_image_bytes,history_snapshots=history),
        **{name: partial(captured_render,getattr(render,name)) for name in (
            'render_pass_progress_image_bytes','render_progress_image_bytes',
            'render_progress_image_bytes_by_list','render_star_progress_image_bytes')})


@matcher.handle()
async def progress_handle(matcher: Matcher, event: Event):
    prepared_command = prepare_progress(CommandContext(match=extract_match(event)), None)
    if isinstance(prepared_command, CommandResult):
        await entry.deliver(matcher,event,prepared_command)
        return
    if prepared_command is None:
        return
    render, dani, catalog = modules()
    request = dani.parse_dani_progress_request(prepared_command[0])
    history_version = dani.DOJO_DATA_VERSION if PROFILE == 'center' else dani.CURRENT_DANI_VERSION
    include_history = bool(request and request['version'] == history_version)
    history_options = {'include_history': include_history}
    if PROFILE == 'center':
        history_options['history_dan_id'] = dani.get_dan_id_by_grade_name(request['grade']) if include_history else None
    actor = entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
    principal, _ = entry.helpers._resolve_requested_identity_key(event)
    provider = entry.create_provider()
    try:
        private = provider.prepare(actor,principal,**history_options)
    except entry.TinfoDenied as error:
        if error.status == 404:
            await entry.helpers._finish_text_reply(matcher,event,entry.helpers._taiko_bind_usage_message(event))
        await entry.helpers._finish_text_reply(matcher,event,'查不到呢，可能不给看哦~')
    except Exception as error:
        accepted = (entry.MergedBindError,entry.TinfoUnavailable) if PROFILE == 'center' else (entry.UserdataProviderError,entry.TinfoUnavailable)
        if not isinstance(error,accepted):
            raise
        try:
            provider.verify_initial()
            await entry.helpers._finish_text_reply(entry.AuthorizedDelivery(matcher,provider,None),event,str(error))
        except (entry.TinfoDenied,entry.TinfoUnavailable):
            await entry.helpers._finish_text_reply(matcher,event,'查不到呢，可能不给看哦~')
    try:
        provider.verify(private)
        delivery = entry.AuthorizedDelivery(matcher,provider,private)
        if PROFILE == 'client':
            from taiko_bot.public_data import ensure_asset_resource_available
            from taiko_bot.settings import get_settings
            ok,message = ensure_asset_resource_available(('core-assets',),get_settings())
            if not ok:
                await entry.helpers._finish_text_reply(delivery,event,message)
        current,history = thaw(private.current),thaw(private.history) or ()
        ports = build_ports(current,history,render,dani,catalog,private.current_failure)
        result = execute_progress(CommandContext(user_id=private.authorized_target.user_id,
            assets_base=str(render.BASE/'assets'),profile=PROFILE),ports,prepared_command)
        provider.verify(private)
        if result is not None:
            await entry.deliver(delivery,event,result)
    except (entry.TinfoDenied,entry.TinfoUnavailable):
        await entry.helpers._finish_text_reply(matcher,event,'授权已失效，请重新查询。' if PROFILE == 'client' else '查不到呢，可能不给看哦~')
