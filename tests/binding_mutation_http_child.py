"""Owned loopback SDK/command smoke; no personal storage or other HTTP origin."""
import ast
import builtins
import json
import os
from pathlib import Path
import re
import sys
import traceback
from types import SimpleNamespace
from functools import wraps
from urllib.parse import urlparse

request=json.loads(sys.stdin.buffer.read(8193))
owned_input=request
origin=urlparse(request['baseUrl'])
assert origin.scheme=='http' and origin.hostname=='127.0.0.1' and origin.port
root=Path(request['ownedRoot']).resolve()
assert str(root).startswith('/var/tmp/') and root.is_dir()
os.environ['TAIKO_BOT_ROOT']=str(root)
os.environ['TAIKO_STORAGE_DIR']=str(root/'sdk-no-storage')
os.environ['PYTHONDONTWRITEBYTECODE']='1'

def guard(path,mode='r'):
    if isinstance(path,(str,bytes,Path)):
        value=str(Path(path).resolve())
        if any(value==p or value.startswith(p+'/') for p in ['/home/sigaer/taiko/userdata','/home/sigaer/taiko-bot/storage','/home/sigaer/git/Sakura_bot/taiko/userdata']):
            raise PermissionError('Private storage forbidden')
        if value.endswith('/taiko-bot/.env') or any(flag in mode for flag in 'wax+'):
            raise PermissionError('SDK child has no file mutation or production configuration permission')
original_open=builtins.open
@wraps(original_open)
def safe_open(path,*args,**kwargs):
    guard(path,args[0] if args else kwargs.get('mode','r'));return original_open(path,*args,**kwargs)
builtins.open=safe_open
original_path_open=Path.open
@wraps(original_path_open)
def safe_path_open(self,*args,**kwargs):
    guard(self,args[0] if args else kwargs.get('mode','r'));return original_path_open(self,*args,**kwargs)
Path.open=safe_path_open

import httpx
class OwnedClient(httpx.Client):
    def send(self,request,**kwargs):
        assert request.url.scheme==origin.scheme and request.url.host==origin.hostname and request.url.port==origin.port
        request.headers['x-forwarded-for']=owned_input['ip']
        return super().send(request,**kwargs)
httpx.Client=OwnedClient
from taiko_bot.binding_mutation_client import remove_center_bind,set_center_bind_visibility
from taiko_bot.viewer_client import fetch_center_bind_info,ViewerClientError
from taiko_runtime.platform_adapter import parse_identity_key
cfg=SimpleNamespace(viewer_base_url=request['baseUrl'],viewer_developer_token=request['token'])

try:
    if request.get('mode')=='command':
        names={'_normalize_identity_key','_center_bind_info_to_entry','_remove_bind_record','_set_taiko_bind_visibility',
               '_resolve_bind_remove_target','_format_multi_bind_summary','_get_bind_ids','_get_selected_bind_slot_number',
               '_has_virtual_bind_slot','_infer_bind_source','_bind_source_label'}
        source=Path(__file__).resolve().parents[1]/'plugins/taiko.py'
        nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
        nodes += [node for node in ast.parse(source.read_text()).body if isinstance(node,ast.FunctionDef) and node.name in names]
        ns={'parse_identity_key':parse_identity_key,'re':re,'_SETTINGS':cfg,'fetch_center_bind_info':fetch_center_bind_info,
            'ViewerClientError':ViewerClientError,'BIND_DELETE_CONFIRM_SESSIONS':{},'BIND_DELETE_CONFIRM_TIMEOUT_SECONDS':300,
            '_now_ts':lambda:1000,'_taiko_bind_usage_message':lambda event:'usage'}
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<owned-client-command>','exec'),ns)
        if request['action']=='remove':result=ns['_remove_bind_record'](request['principal'],request.get('target',''),force_last=request.get('forceLast',False))
        else:result=ns['_set_taiko_bind_visibility'](request['principal'],request['visible'])
        result={'reply':result,'confirmation':ns['BIND_DELETE_CONFIRM_SESSIONS'].get(request['principal'])}
    elif request['action']=='remove':
        result=remove_center_bind(request['principal'],request['taikoId'],force_last=request.get('forceLast',False),request_id=request.get('requestId'),settings=cfg)
        result={key:value for key,value in result.items() if key!='binding'}
    else:
        result=set_center_bind_visibility(request['principal'],request['visible'],request_id=request.get('requestId'),settings=cfg)
        result={key:value for key,value in result.items() if key!='binding'}
    print(json.dumps({'ok':True,'result':result},ensure_ascii=False))
except ViewerClientError as error:
    print(json.dumps({'ok':False,'status':error.status_code,'message':str(error)},ensure_ascii=False))
except Exception as error:
    sites=[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
           for frame in traceback.extract_tb(error.__traceback__)[-4:]]
    print(json.dumps({'ok':False,'diagnostic':{'type':type(error).__name__,'sites':sites}}))
