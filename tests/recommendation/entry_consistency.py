"""Installed actual Bot matcher/provider/command regression; pixels are a boundary.

--root is the same synthetic catalog/Publication root used by Web HTTP tests.
No source-path imports, editable installs, production reads, SQL or messages.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import types

p = argparse.ArgumentParser()
p.add_argument('--root', type=Path, required=True)
p.add_argument('--user', required=True)
p.add_argument('--profile', choices=('center', 'client'), default='center')
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
os.chdir(a.root)
os.environ.update(TAIKO_BOT_ROOT=str(a.root), TAIKO_CENTER_ROOT=str(a.root),
                  TAIKO_OFFLINE_ROOT=str(a.root), TAIKO_USERDATA_DIR=str(a.root/'userdata'),
                  TAIKO_RUNTIME_ENV_FILE=str(a.root/'absent.env'),
                  TAIKO_VIEWER_BASE_URL='https://fixture.invalid',
                  TAIKO_VIEWER_DEVELOPER_TOKEN='synthetic', MPLCONFIGDIR=str(a.root/'mpl'))

def guard(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise AssertionError('Bot network forbidden')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0])
        if path.startswith(('/home/sigaer/taiko/userdata', '/home/sigaer/taiko/songs', '/etc/taiko')):
            raise AssertionError('Production data forbidden')
sys.addaudithook(guard)

import nonebot
nonebot.init(driver='~fastapi+~httpx', log_level='CRITICAL', taiko_song_profile=a.profile,
             taiko_song_public_root=str(a.root))
assert nonebot.load_plugin('taiko_bot.runtime.public')
player = nonebot.load_plugin('taiko_bot.runtime.player.entry')
assert player
entry = player.module
from nonebot.adapters.onebot.v11 import Adapter, Bot, Message, GroupMessageEvent
from nonebot.matcher import matchers
from nonebot.message import handle_event, run_postprocessor
from taiko_application.query import RecommendationContext
from taiko_application.query.recommendation import project_ordinary_recommendations
from taiko_bot.runtime.player import recommendation as rec, b30
from taiko_store.reader import read_current_json

state = {'visible': True, 'unbound': False}
if a.profile == 'center':
    def connection():
        class Cursor:
            def execute(self, sql, params):
                assert sql.strip().startswith('SELECT') and 'FOR UPDATE' not in sql
                self.principal = params[0]
            def fetchall(self):
                return [] if state['unbound'] else [(1, self.principal, a.user, 1, 1, 'wahlap', int(state['visible']))]
            def fetchone(self): return self.principal, 0
            def close(self): pass
        return types.SimpleNamespace(cursor=Cursor, commit=lambda: None, close=lambda: None)
    entry.get_taiko_db_connection = connection
else:
    from taiko_bot.runtime.player.client import provider
    from taiko_bot.viewer_client import CenterBindSlot, ViewerClientError
    from taiko_bot import userdata_provider, public_data
    from taiko_bot.private_read_client import PrivateReadReply
    def info(principal, settings=None):
        if state['unbound']: return None
        return {'id': a.user, 'visible': int(state['visible']), 'currentSlot': 1,
                'currentSource': 'wahlap', 'bindings': [CenterBindSlot(1, a.user, int(state['visible']), True, 'wahlap')]}
    provider.fetch_center_bind_info = info
    def remote(kind, source, **kwargs):
        assert kind == 'current' and source == a.user
        if not state['visible']: raise ViewerClientError('revoked', status_code=403)
        return PrivateReadReply(read_current_json(a.root/'userdata', a.user), None, source_view={'kind':'fixture'})
    userdata_provider.fetch_private_read = remote
    public_data.ensure_asset_resource_available = lambda *args, **kwargs: (True, '')

for module in list(sys.modules.values()):
    if getattr(module, '__name__', '').endswith('feature_handler.feature_handler'):
        module.is_feature_enabled = lambda *args, **kwargs: True
        module.is_group_allowed = lambda *args, **kwargs: True

observed = {}
def render_recommendation(rows, **kwargs):
    observed['recommendations'] = project_ordinary_recommendations(RecommendationContext(rows=rows, basis='rating'))
    return b'fixture-render-boundary'
rec.support().generate_recommend_image = render_recommendation
score = b30.modules()[1]
real_render = score.generate_top_N_image
real_dims, real_aggregate = score.compute_dim_topN_means, score.aggregate_topN_value
def dims(results, n):
    value = real_dims(results, n)
    observed['dimensions'] = value
    return value
def aggregate(results, col, n):
    value = real_aggregate(results, col, n)
    observed['rating'] = value
    return value
def render_rating(results, *args, **kwargs):
    observed['charts'] = [(x.song_id, x.level) for x in results]
    kwargs['font_path'] = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return real_render(results, *args, **kwargs)
score.compute_dim_topN_means = dims
score.aggregate_topN_value = aggregate
score.generate_top_N_image = render_rating

nonebot.get_driver().register_adapter(Adapter)
bot = Bot(nonebot.get_adapter(Adapter), '90000')
sent, errors = [], []
async def send(self, event, message, **kwargs):
    sent.append('image' if 'image' in str(message) else 'text')
    return {'message_id': 1}
bot.send = types.MethodType(send, bot)
@run_postprocessor
async def post(exception: Exception | None):
    if exception: errors.append(type(exception).__name__)

async def dispatch(matcher, text):
    for key in list(matchers): matchers[key] = []
    matchers[matcher.priority] = [matcher]
    sent.clear(); errors.clear()
    msg = Message(text+'[CQ:at,qq=12345]')
    event = GroupMessageEvent(time=1, self_id=90000, post_type='message', message_type='group',
        sub_type='normal', message_id=1, user_id=67890, group_id=123, message=msg,
        original_message=msg, raw_message=str(msg), font=0,
        sender={'user_id':67890, 'nickname':'fixture'}, to_me=True)
    await handle_event(bot, event)
    assert not errors, errors
    assert sent, 'no command delivery'

async def run():
    await dispatch(rec.taikorec, 'taikorec rating 20')
    assert 'recommendations' in observed
    await dispatch(b30.taikob, 'taikob20 v1 -r' if a.profile == 'center' else 'taikob20 -r')
    current = read_current_json(a.root/'userdata', a.user)
    observed['hasRating'] = 'rating' in observed
    state['visible'] = False
    observed.pop('recommendations', None)
    await dispatch(rec.taikorec, 'taikorec rating 20')
    assert 'recommendations' not in observed, 'denied query reached computation'
    state['visible'] = True
    await dispatch(rec.taikorec, 'taikorec rating 20')
    # A second command in the same process reuses the real provider and caches.
    baseline = json.loads(json.dumps(observed))
    catalog_path = a.root/'songs/song_data.json'
    original = catalog_path.read_text()
    catalog = json.loads(original)
    catalog[26].update(song_name=catalog[25]['song_name'], song_name_jp=catalog[25]['song_name_jp'])
    if a.profile == 'center':
        summary = b30.modules()[3]
        _, rating_index, const_table = summary._load_rating_resources(str(a.root/'songs/rating_structured_with_ids.json'))
        detail_count = len(summary._pick_top_entries(current['songs'], rating_index, const_table, 50, collapse_duplicate_versions=True))
        catalog[1].update(song_name=catalog[0]['song_name'], song_name_jp=catalog[0]['song_name_jp'])
    try:
        catalog_path.write_text(json.dumps(catalog))
        await dispatch(rec.taikorec, 'taikorec rating 20')
        ids = [x['songId'] for x in observed['recommendations']['items']]
        assert not (10025 in ids and 10026 in ids), 'catalog update retained old duplicate groups'
        if a.profile == 'center' and all(any(x['song_no']==sid and x['level']==4 for x in current['songs']) for sid in (10000,10001)):
            updated_count=len(summary._pick_top_entries(current['songs'], rating_index, const_table, 50, collapse_duplicate_versions=True))
            assert updated_count==detail_count-1, 'B30 details retained import-time groups'
    finally:
        catalog_path.write_text(original)
    await dispatch(rec.taikorec, 'taikorec rating 20')
    assert observed['recommendations'] == baseline['recommendations'], 'catalog switch back retained stale groups'
    observed['catalogRefresh'] = True
    a.output.write_text(json.dumps(observed))
    print('Installed Bot matcher '+a.profile+': PASS')
asyncio.run(run())
