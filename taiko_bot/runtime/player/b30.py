"""B30 commands owned by the player runtime; all score inputs are captured."""
import re
from functools import partial
from importlib import import_module
from nonebot import on_message, on_regex
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from taiko_application.commands import CommandContext, CommandResult, B30Ports, prepare_b30, execute_b30
from taiko_application.private_input import thaw
from . import entry

PROFILE = entry.profile()
PATTERN = re.compile(r'^/?taikob(?:\s*(50|[1-4]\d|[1-9]))?(?:\s*(.*))?$' if PROFILE == 'center'
                     else r'^/?taikob\s*(50|[1-4]\d|[1-9])(?:\s*(.*))?$', re.IGNORECASE)

def extract_match(event):
    return PATTERN.match(entry.helpers.extract_plain_text(event).strip())

async def eligible(event: Event):
    return extract_match(event) is not None

taikob = (on_message(rule=entry.feature_on('taiko') & Rule(eligible)) if PROFILE == 'center'
          else on_regex(PATTERN.pattern, flags=re.IGNORECASE, rule=entry.feature_on('taiko')))

def modules():
    return tuple(import_module(f'.{PROFILE}.b30_support.{name}', __package__)
                 for name in ('parsing','score_calculator','dimension','b30_render','taikob_v2'))

def build_ports(private=None, *, provider=None):
    parsing, score, dimension, summary, v2 = modules()
    current = thaw(private.current) if private else None
    prepared_inputs = dict(getattr(provider,"b30_inputs",{}))
    if private is not None:prepared_inputs["history_snapshots"] = thaw(private.history) or ()
    snapshot = getattr(provider,"b30_snapshot",None)
    preparation_error = getattr(provider,"b30_preparation_error",None)
    def records():
        if private and private.current_failure:
            if private.current_failure.missing:
                raise FileNotFoundError('userdata not found')
            raise ValueError(private.current_failure.message)
        return current.get('songs', []) if isinstance(current,dict) else current
    def compute(_user_id, **options):
        data=records()
        return score.compute_all_from_userdata_records(data, **options) if PROFILE == 'center' else score.compute_all_from_userdata_records(data)
    def summary_image(user_id, **options):
        if PROFILE == "client":options.pop("collapse_duplicate_versions",None)
        records()
        if preparation_error is not None:raise preparation_error
        return summary.render_b30_image(user_id, userdata=current, **prepared_inputs, **options)
    def v2_image(function,user_id,**options):
        records()
        if preparation_error is not None:raise preparation_error
        extra = {'snapshot':snapshot} if PROFILE == 'center' else {}
        if PROFILE == 'center' and function is v2.render_b20_v2_image:extra.update(prepared_inputs)
        return function(user_id,userdata=current,**extra,**options)
    from ..public.config import root
    return B30Ports(TAIKOB_FONT_PATH=str(root()/'assets/fonts/DDFont.ttf'),
        TAIKOB_V2_DIM_USAGE=parsing.TAIKOB_V2_DIM_USAGE,
        V2DataSourceError=import_module('.center.taikob_v2_data',__package__).V2DataSourceError if PROFILE=='center' else RuntimeError,
        V2_TAIKOB_DIM_ALIASES=v2.V2_TAIKOB_DIM_ALIASES,
        _extract_rating_version=getattr(parsing,'_extract_rating_version',None),
        _load_user_song_records=lambda _:records(),
        _parse_taikob_dim_arg=parsing._parse_taikob_dim_arg,
        _resolve_taikob_dim_arg=parsing._resolve_taikob_dim_arg,
        _to_jpeg_bytes=parsing._to_jpeg_bytes,
        compute_all_from_userdata=compute,
        generate_dim_top_image=partial(dimension.generate_dim_top_image,userdata=current),
        generate_top_N_image=partial(score.generate_top_N_image,observed_at=getattr(provider,'b30_observed_at',None)),
        render_b20_v2_image=partial(v2_image,v2.render_b20_v2_image),
        render_b20_v2_dim_image=partial(v2_image,v2.render_b20_v2_dim_image),
        render_b30_image=summary_image)

@taikob.handle()
async def taikob_handle(matcher: Matcher, event: Event):
    command=prepare_b30(CommandContext(match=extract_match(event),profile=PROFILE),build_ports())
    if isinstance(command,CommandResult):
        await entry.deliver(matcher,event,command)
        return
    actor=entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
    principal,_=entry.helpers._resolve_requested_identity_key(event)
    provider=entry.create_provider()
    try:
        private=provider.prepare_b30(actor,principal,command)
    except entry.TinfoDenied as error:
        if error.status==404:
            await entry.helpers._finish_text_reply(matcher,event,entry.helpers._taiko_bind_usage_message(event))
        await entry.helpers._finish_text_reply(matcher,event,'查不到呢，可能不给看哦~')
    except Exception as error:
        accepted=(entry.MergedBindError,entry.TinfoUnavailable) if PROFILE=='center' else (entry.UserdataProviderError,entry.TinfoUnavailable)
        if not isinstance(error,accepted):raise
        try:
            provider.verify_initial()
            await entry.helpers._finish_text_reply(entry.AuthorizedDelivery(matcher,provider,None),event,str(error))
        except (entry.TinfoDenied,entry.TinfoUnavailable):
            await entry.helpers._finish_text_reply(matcher,event,'查不到呢，可能不给看哦~')
    try:
        provider.verify(private)
        delivery=entry.AuthorizedDelivery(matcher,provider,private)
        if PROFILE=='client':
            from taiko_bot.public_data import ensure_asset_resource_available
            from taiko_bot.settings import get_settings
            ok,message=ensure_asset_resource_available(('core-assets','cover-assets','dress-assets','nameplate-assets'),get_settings())
            if not ok:await entry.helpers._finish_text_reply(delivery,event,message)
        result=execute_b30(CommandContext(user_id=private.authorized_target.user_id,profile=PROFILE),
                           build_ports(private,provider=provider),command)
        provider.verify(private)
        if result is not None:await entry.deliver(delivery,event,result,rating_v2=command[2])
    except (entry.TinfoDenied,entry.TinfoUnavailable):
        await entry.helpers._finish_text_reply(matcher,event,'授权已失效，请重新查询。' if PROFILE=='client' else '查不到呢，可能不给看哦~')
