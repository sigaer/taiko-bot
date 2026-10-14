"""Run existing storage assertions against the relocated, installed implementation."""
import os, sys, types
from pathlib import Path
root=Path(sys.argv[1]).resolve()
os.chdir(root)
os.environ['TAIKO_RUNTIME_ENV_FILE']='/var/tmp/taiko-phase2fe-20261014/absent.env'
for name,part in [('plugins','plugins'),('plugins.utils','plugins/utils')]:
 m=types.ModuleType(name);m.__path__=[str(root/part)];sys.modules[name]=m
attempts=[]
def guard(event,args):
 if event in ('socket.connect','socket.getaddrinfo','sqlite3.connect'):
  attempts.append(event);raise AssertionError(event)
 if event=='open' and isinstance(args[0],str) and args[0].startswith(('/home/sigaer/','/etc/taiko','/opt/')):
  attempts.append(args[0]);raise AssertionError('production read')
sys.addaudithook(guard)
if __name__ == '__main__':
    import pytest
    names=['test_merged_bind.py','test_merged_private_read.py','test_merged_materialization.py','test_merge_kernel_decoupling.py','test_publication_store.py']
    result=pytest.main(['-q','-x','--basetemp=/var/tmp/taiko-phase2fe-20261014/storage-tmp',*[str(root/'tests'/n) for n in names]])
    assert not attempts
    raise SystemExit(result)
