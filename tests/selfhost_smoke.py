"""Run with the freshly installed client Python under the memory QA runner."""
import os, tempfile, time
from pathlib import Path
from importlib.metadata import version
root = Path(tempfile.mkdtemp(prefix='fresh-client-', dir=os.environ.get('QA_RUN_TMPDIR', os.environ.get('TMPDIR'))))
os.chdir(root)
os.environ.update(TAIKO_RUNTIME_ROOT=str(root), TAIKO_SONG_PROFILE='client', TAIKO_RUNTIME_ENV_FILE=str(root/'absent.env'), MPLCONFIGDIR=str(root/'mpl'), XDG_CACHE_HOME=str(root/'cache'), LOG_LEVEL='WARNING')
from taiko_bot.bootstrap import create_app
app = create_app()
import nonebot
names={p.module_name for p in nonebot.get_loaded_plugins()}
assert 'nonebot_plugin_method_calls' not in names
assert 'taiko_bot.runtime.player.entry' in names
assert 'taiko_bot.runtime.community.community_entry' in names
import taiko_runtime_init as init
# Avoid downloading the large production asset bundle during isolated startup QA.
init.sync_public_datasets_once=lambda settings:{'downloaded':[]}
init.start_background_asset_sync=lambda settings:None
from fastapi.testclient import TestClient
with TestClient(app) as client:
    response=client.get('/local-api/health')
    assert response.status_code==200
    with client.websocket_connect('/onebot/v11/ws', headers={'x-self-id':'100001','x-client-role':'Universal'}) as ws:
        ws.send_json(dict(time=int(time.time()),self_id=100001,post_type='meta_event',meta_event_type='lifecycle',sub_type='connect'))
        ws.send_json(dict(time=int(time.time()),self_id=100001,post_type='message',message_type='private',sub_type='friend',user_id=12345,message_id=1,font=0,sender={'user_id':12345,'nickname':'Synthetic'},message=[{'type':'text','data':{'text':'青春达人'}}],raw_message='青春达人'))
        for _ in range(10):
            request=ws.receive_json()
            action=request['action']
            data={'message_id':1}
            if action=='get_login_info':data={'user_id':100001,'nickname':'Synthetic Bot'}
            ws.send_json({'status':'ok','retcode':0,'data':data,'echo':request.get('echo')})
            if action in ('send_private_msg','send_msg'):
                assert request['params']['user_id']==12345
                break
        else:raise AssertionError('Event produced no reply')
assert (root/'storage/data/taiko.sqlite3').exists() or list((root/'storage/data').rglob('*.db'))
print('clean-client-startup-and-OneBot-reply PASS', version('taiko-bot'), 'plugins', len(names))
