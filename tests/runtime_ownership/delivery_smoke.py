"""Nine installed public entries on both transports; synthetic/public inputs only.
Not a replacement for the retained frozen parity matrix.
"""
import argparse, asyncio, hashlib, json, os, shutil, sys, types
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--host', choices=['center', 'client'], required=True)
p.add_argument('--work', type=Path, required=True)
p.add_argument('--assets', type=Path, required=True)
a = p.parse_args()
a.work.mkdir(parents=True, exist_ok=True)
archive = Path(__file__).resolve().parents[1] / 'archive/public-song-plugin/tests'
(a.work / 'songs').mkdir(exist_ok=True)
for src in (archive / 'fixtures').glob('*.json'):
    shutil.copyfile(src, a.work / 'songs' / src.name)
for name in ('rating_structured_with_ids.json', 'analyze_result_filtered.json'):
    shutil.copyfile(archive / 'catalog-fixtures' / name, a.work / 'songs' / name)
(a.work / 'assets').symlink_to(a.assets, target_is_directory=True)
os.chdir(a.work)
os.environ.update(TAIKO_BOT_ROOT=str(a.work), TAIKO_CENTER_ROOT=str(a.work),
                  TAIKO_RUNTIME_ENV_FILE=str(a.work / 'absent.env'))
violations = []
def guard(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'sqlite3.connect'):
        violations.append(event); raise AssertionError(event)
    if event == 'open' and isinstance(args[0], str) and args[0].startswith(('/home/sigaer/', '/opt/', '/etc/taiko')):
        violations.append('production file'); raise AssertionError('production file')
sys.addaudithook(guard)
from PIL import Image
Image.init()
import nonebot
nonebot.init(driver='~fastapi+~httpx', log_level='CRITICAL', taiko_song_profile=a.host,
             taiko_song_public_root=str(a.work))
public = nonebot.load_plugin('taiko_bot.runtime.public')
player = nonebot.load_plugin('taiko_bot.runtime.player.entry')
assert public and player and len(public.matcher) == 9 and len(player.matcher) == (21 if a.host=="center" else 18)
from nonebot.adapters.onebot.v11 import Adapter, Bot, Message, GroupMessageEvent
from nonebot.adapters.qq import Adapter as QQAdapter, Bot as QQBot
from nonebot.adapters.qq.config import BotInfo
from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
from nonebot.message import handle_event, run_postprocessor
for m in list(sys.modules.values()):
    if getattr(m, '__name__', '').endswith('feature_handler.feature_handler'):
        m.is_feature_enabled = lambda *args, **kw: True
        m.is_group_allowed = lambda *args, **kw: True
public.module.provider.asset_ready = lambda: (True, '')
public.module.provider.alias_assets_ready = lambda: (True, '')
nonebot.get_driver().register_adapter(Adapter)
nonebot.get_driver().register_adapter(QQAdapter)
bot = Bot(nonebot.get_adapter(Adapter), '90000')
qq = QQBot(nonebot.get_adapter(QQAdapter), '90000', BotInfo(id='90000', token='fixture', secret='fixture'))
sent, errors, results = [], [], []
async def send(self, event, message, **kwargs):
    sent.append(str(message)); return {'message_id': 1}
bot.send = types.MethodType(send, bot)
qq.send = types.MethodType(send, qq)
@run_postprocessor
async def post(exception: Exception | None):
    if exception: errors.append((type(exception).__name__, str(exception)))
cases = {
    'what_song': 'id1367是什么歌', 'alias_query': 'id1367有什么别名',
    'song_where': 'id1367歌在哪', 'song_position_phrase': 'id1367在什么位置',
    'song_pos_by_id': '位置1367', 'diff_by_id': '鬼1367',
    'note_count': '太鼓查物量872', 'const_query': '查定数6.6', 'patterns': '查配置180',
}
async def run():
    for platform in ('onebot', 'qq'):
        for name, text in cases.items():
            if name == 'what_song' and platform == 'qq': text = 'taiko ' + text
            sent.clear(); errors.clear()
            if platform == 'onebot':
                msg = Message(text)
                event = GroupMessageEvent(time=1, self_id=90000, post_type='message', message_type='group',
                    sub_type='normal', message_id=1, user_id=10001, group_id=123, message=msg,
                    original_message=msg, raw_message=text, font=0, sender={'user_id':10001}, to_me=True)
                target = bot
            else:
                event = GroupAtMessageCreateEvent(id='fixture', content=text, timestamp='2026-10-14T00:00:00+00:00',
                    author={'id':'fixture-user','member_openid':'fixture-user','bot':False,'member_role':'member'},
                    group_id='fixture-group', group_openid='fixture-group', to_me=True)
                target = qq
            await handle_event(target, event)
            assert sent and not errors, (name, platform, errors)
            results.append({'entry': name, 'platform': platform, 'sends': len(sent),
                            'output_sha256': hashlib.sha256('\n'.join(sent).encode()).hexdigest()})
asyncio.run(run())
assert not violations, violations
(a.work / 'result.json').write_text(json.dumps({'host': a.host, 'cases': results, 'violations': violations}, indent=2))
print(a.host, len(results), 'PASS; public and player matcher ownership')
