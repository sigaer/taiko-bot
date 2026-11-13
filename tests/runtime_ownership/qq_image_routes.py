"""Full community registration and image routes, synthetic bytes and no IO."""
import argparse
import asyncio
from io import BytesIO
import json
import os
from pathlib import Path
import sys

p=argparse.ArgumentParser()
p.add_argument('--host',choices=['center','client'],required=True)
p.add_argument('--work',type=Path,required=True)
args=p.parse_args()
args.work.mkdir(parents=True,exist_ok=False)
os.chdir(args.work)
os.environ.update(TAIKO_BOT_ROOT=str(args.work),TAIKO_CENTER_ROOT=str(args.work),
    TAIKO_RUNTIME_ROOT=str(args.work),TAIKO_RUNTIME_ENV_FILE=str(args.work/'absent.env'),
    QQ_MARKDOWN_IMAGE_CACHE_DIR=str(args.work/'media'),
    QQ_MARKDOWN_IMAGE_BASE_URL='https://fixture.invalid/cache')

violations=[]
def guard(event,data):
    if event in ('socket.connect','socket.getaddrinfo','sqlite3.connect'):
        violations.append(event)
        raise AssertionError('external IO prohibited')
    if (event=='open' and isinstance(data[0],str)
            and data[0].startswith(('/home/sigaer/taiko/','/etc/taiko'))
            and not data[0].startswith(str(args.work)+'/')):
        violations.append('production file')
        raise AssertionError('production file prohibited')
sys.addaudithook(guard)

import nonebot
nonebot.init(driver='~fastapi+~httpx',log_level='ERROR',taiko_song_profile=args.host,taiko_song_public_root=str(args.work))
plugin=nonebot.load_plugin('taiko_bot.runtime.community.community_entry')
assert plugin
from importlib import import_module
from nonebot.exception import FinishedException
from PIL import Image
module=import_module(f'taiko_bot.runtime.community.{args.host}.draw_guess')
stream=BytesIO()
Image.new('RGB',(12,24),'blue').save(stream,'PNG')
payload=stream.getvalue()

class Matcher:
    def __init__(self):self.messages=[]
    async def send(self,message):self.messages.append(message)
    async def finish(self,message=None,**kwargs):
        if message is not None:self.messages.append(message)
        raise FinishedException

class QQEvent:
    __module__='nonebot.adapters.qq.event'
    id='fixture-event'
    group_openid='fixture-group'

async def run():
    for event in (QQEvent(),object()):
        matcher=Matcher()
        try:
            await module._finish_image_reply(matcher,event,BytesIO(payload),prefix_text='fixture caption')
        except FinishedException:
            pass
        assert len(matcher.messages)==1
        types=[s.type for s in matcher.messages[0]]
        if isinstance(event,QQEvent):
            assert types==['markdown'],types
            content=matcher.messages[0][0].data['markdown'].content
            assert 'fixture caption' in content and 'img#12px #24px' in content
        elif args.host=='client':
            assert types==['image','text'],types
        else:
            assert types==['text','image'],types
asyncio.run(run())
assert not violations,violations
print(json.dumps(dict(status='PASS',host=args.host,community_matchers=len(plugin.matcher),
    QQ='Markdown image and caption',OneBot='original caption ordering',external_IO=False)))
