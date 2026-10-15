"""Shared captured-player access and delivery for the query/display cluster."""
from . import entry
from taiko_application.private_input import thaw

async def prepare(matcher, event, *, summary=False):
    actor = entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
    principal, _ = entry.helpers._resolve_requested_identity_key(event)
    provider = entry.create_provider()
    try:
        private = provider.prepare(actor, principal, **({"summary_command": True} if summary and entry.profile()=="center" else {}))
        if summary and entry.profile()=="client":
            from datetime import datetime
            provider.summary_utime = str(datetime.now().replace(microsecond=0))
    except entry.TinfoDenied as error:
        text = entry.helpers._taiko_bind_usage_message(event) if error.status == 404 else '查不到呢，可能不给看哦~'
        await entry.helpers._finish_text_reply(matcher, event, text)
        return
    except Exception as error:
        try:
            provider.verify_initial()
            await entry.helpers._finish_text_reply(entry.AuthorizedDelivery(matcher, provider, None), event, str(error))
        except (entry.TinfoDenied, entry.TinfoUnavailable):
            await entry.helpers._finish_text_reply(matcher, event, '查不到呢，可能不给看哦~')
        return
    provider.verify(private)
    return provider, private, entry.AuthorizedDelivery(matcher, provider, private)


def score_record(current, song_id, level):
    return entry.presentation._collect_entries_for_song((current or {}).get('songs', []), song_id).get(level)

async def ensure_assets(matcher, event, *resource_names):
    from taiko_bot.public_data import ensure_asset_resource_available
    from taiko_bot.settings import get_settings
    ok, message = ensure_asset_resource_available(resource_names, get_settings())
    if ok:
        return True
    await entry.helpers._finish_text_reply(matcher,event,message)
    return False

from nonebot.adapters import Event as MessageEvent
from nonebot.matcher import Matcher
_finish_text_reply = entry.helpers._finish_text_reply

def find_player(user_id):
    return entry.query_cluster.find_player(user_id)

async def quick_actions_panel_handle(event: MessageEvent, matcher: Matcher):
    await _finish_text_reply(matcher, event, '快捷操作面板：点击下方按钮可快速填入常用指令。', quick_actions=True)

async def twso_handle(event: MessageEvent, matcher: Matcher):
    try:
        provider, private, twso = await prepare(matcher, event, summary=False)
        bind_target = {'user_id': private.authorized_target.user_id, 'is_virtual': len(private.authorized_target.members) > 1 or private.authorized_target.user_id.startswith('u0')}
        user_id = str(bind_target['user_id'])
        if private.current_failure:
            if private.current_failure.missing:
                raise FileNotFoundError(2, 'No such file or directory', str(provider._root / f'{user_id}data.json'))
            raise ValueError(private.current_failure.message)
        target_music_list = [1384, 354, 979, 1277, 412, 283, 194, 835, 518, 463]
        target_title_list = ["YOU're your HERO", '埼玉2000', '震天动地！太鼓之达人', '打破空想', 'Night of Knights / Knight of Nights', '初音未来的消失-剧场版-', 'Ignis Danse', "What's in the box?", '!!!Chaos Time!!!', '幽玄之乱']
        result_list = []
        for id in target_music_list:
            res = score_record(thaw(private.current), id, 4)
            result_list.append(res if res else None)
        res = '目前课题曲最高分数一览：\n'
        for index in range(0, 10):
            res += f"{index + 1}.{target_title_list[index]}：{(result_list[index]['high_score'] if result_list[index] else '未游玩')}\n"
        total_score = sum(list(map(lambda x: x['high_score'] if x else 0, result_list)))
        res += f'总和：{total_score}\n\n'
        try:
            if isinstance(bind_target, dict) and bind_target.get('is_virtual'):
                res += 'u0 合并账户不提供活动排行信息'
            else:
                score_dict = find_player(str(user_id))
                res += f"昵称：{score_dict['mydon_name']}\n全球排名：{score_dict['rank']}\n国内排名：{score_dict['cn_rank']}\n活动记录总分：{score_dict['total_score']}\n"
        except Exception as e:
            res += '未查询到参与活动信息，可能未报名活动'
        await _finish_text_reply(twso, event, res)
    except (entry.TinfoDenied, entry.TinfoUnavailable):
        await entry.helpers._finish_text_reply(matcher, event, '查不到呢，可能不给看哦~')
