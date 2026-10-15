import os, sys
from pathlib import Path
fixture = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else Path.cwd()
os.environ.update(TAIKO_RUNTIME_ENV_FILE=str(fixture/'absent.env'),
                  TAIKO_BOT_ROOT=str(fixture), TAIKO_CENTER_ROOT=str(fixture))

def guard(event,args):
 if event in ('socket.connect','socket.getaddrinfo','sqlite3.connect'):raise AssertionError(event)
 if event=='open' and isinstance(args[0],str) and args[0].startswith(('/home/sigaer','/etc/taiko','/opt/')):raise AssertionError('production read')
sys.addaudithook(guard)
import nonebot
nonebot.init(driver='~fastapi+~httpx',log_level='ERROR',taiko_song_profile=sys.argv[1])
mode=sys.argv[2] if len(sys.argv)>2 else 'reverse'
if mode=='all':
 nonebot.load_all_plugins(['taiko_bot.runtime.player.entry','taiko_bot.runtime.public','feature_handler'],[])
 b=nonebot.get_plugin('entry');a=nonebot.get_plugin('public')
elif mode=='forward':
 a=nonebot.load_plugin('taiko_bot.runtime.public');b=nonebot.load_plugin('taiko_bot.runtime.player.entry')
else:
 b=nonebot.load_plugin('taiko_bot.runtime.player.entry');a=nonebot.get_plugin('public')
assert a and b
assert len(a.matcher)==9 and len(b.matcher)==(49 if sys.argv[1]=="center" else 45)
print('PASS',sys.argv[1],mode, len(a.matcher),len(b.matcher))
assert nonebot.require('taiko_bot.runtime.public') is a.module
assert nonebot.require('taiko_bot.runtime.player.entry') is b.module
assert len(a.matcher)==9 and len(b.matcher)==(49 if sys.argv[1]=="center" else 45)
