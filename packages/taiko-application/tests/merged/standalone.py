import importlib.abc
import json
import sys
from datetime import datetime
class NoHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'plugins','taiko_store','pymysql','sqlite3','nonebot'}:
            raise AssertionError('host dependency: '+fullname)
sys.meta_path.insert(0, NoHost())
from taiko_application import merged_bind as m
calls=[]
def guard(event,args):
    if event in {'open','socket.connect','socket.getaddrinfo','sqlite3.connect'}:
        calls.append(event)
        raise AssertionError('kernel IO')
sys.addaudithook(guard)
result=m._merge_payloads([{'songs':[{'song_no':7,'level':4,'stage_cnt':2}]}], profile_source={'profile':{'name':'synthetic'}},merge_topology=['222','111'],combo_map={(7,4):100},clock=lambda:datetime(2025,1,1))
assert result['_meta']['ts']=='2025-01-01 00:00:00' and result['songs'][0]['stage_cnt']==2 and not calls
print(json.dumps({'status':'PASS','blocked_host_imports':True,'all_execution_file_network_sql_IO_forbidden':True}))
