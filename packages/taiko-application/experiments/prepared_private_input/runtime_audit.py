"""Fresh-process import guard and zero IO during prepared execution."""
import builtins
import importlib.abc
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
violations=[]
def forbidden(name):
    return any(p in {'taiko_store','merged_bind','plugins','host_fixture','oracle'} or 'userdata' in p.lower() or 'writer' in p.lower() for p in name.split('.'))
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if forbidden(fullname):
            violations.append(fullname)
            raise AssertionError('Forbidden runtime dependency')
sys.meta_path.insert(0,Guard())
from prepared_private_input.application_adapter import execute_prepared_score
from prepared_private_input.dto import PreparedPrivateInput, AuthorizedTarget, Provenance
from PIL import Image
Image.init()  # Public codecs load before the measured no-IO execution window.
from importlib.metadata import version
assert version('taiko-application')=='0.6.0'
assert not any(forbidden(n) for n in sys.modules)
active=False
def audit(event,args):
    if active and event in {'open','os.listdir','os.scandir','socket.connect','socket.getaddrinfo','sqlite3.connect','subprocess.Popen','os.system'}:
        violations.append(event)
        raise AssertionError('Prepared execution attempted IO')
sys.addaudithook(audit)
active=True
for members,profile in [(('111',),'111'),(('111','222'),'111'),(('111','333'),'111'),(('111','222'),'222')]:
    p=PreparedPrivateInput(AuthorizedTarget('fixture','fixture','u0_fixture',members,profile,'auth-1'),
        {'profile':{'mydon_name':profile},'songs':[{'song_no':7,'high_score':900000,'stage_cnt':3}]},None,
        Provenance('synthetic-u0','view-1',None,members,profile,'rule-1'))
    result=execute_prepared_score(p,'tinfo Neon')
    assert result.kind=='image' and len(result.payload)>0
    assert execute_prepared_score(p,'tinfo none').kind=='text'
active=False
assert not violations,violations
print(json.dumps({'status':'PASS','forbidden_import_attempts':violations,'execution_IO_attempts':0,'prepared_executions':8,'application':'0.6.0'}))
