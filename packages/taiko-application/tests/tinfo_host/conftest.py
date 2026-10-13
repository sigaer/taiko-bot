"""Fail on attempted production/network/DB access, even if application catches it."""
import builtins
import os
from pathlib import Path
import sys
import pytest

ATTEMPTS=[]
APPLICATION=False
original_import=builtins.__import__


def guarded_import(name,*args,**kwargs):
    if APPLICATION and any(x in name.lower() for x in ('taiko_store','merged_bind','userdata','writer','plugins')):
        ATTEMPTS.append('application import '+name)
        raise AssertionError(ATTEMPTS[-1])
    return original_import(name,*args,**kwargs)


def audit(event,args):
    if APPLICATION and event in ('os.listdir','os.scandir'):
        path=Path(args[0]).resolve()
        roots=(Path(sys.prefix),Path('/usr/lib/python3.11'),Path(__file__).resolve().parents[2]/'src',Path(os.environ['TINFO_ASSETS']).resolve(),Path('/usr/share/fonts'))
        if not any(path.is_relative_to(root) for root in roots):
            ATTEMPTS.append('application directory '+str(path))
            raise AssertionError(ATTEMPTS[-1])
    if APPLICATION and event in ('os.remove','os.rename','os.mkdir','os.rmdir','os.symlink','os.link','os.truncate','os.chmod','os.utime'):
        ATTEMPTS.append('application '+event)
        raise AssertionError(ATTEMPTS[-1])
    if event.startswith(('socket.connect','socket.getaddrinfo','sqlite3.connect','subprocess.')):
        ATTEMPTS.append(event)
        raise AssertionError(event)
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        path=Path(os.fsdecode(args[0])).resolve()
        if str(path).startswith(('/home/sigaer/','/opt/','/etc/taiko')):
            ATTEMPTS.append('production '+str(path))
            raise AssertionError(ATTEMPTS[-1])
        if APPLICATION:
            flags=args[2] if len(args)>2 else 0
            if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):
                ATTEMPTS.append('application write')
                raise AssertionError(ATTEMPTS[-1])
            code_roots=(Path(sys.prefix),Path('/usr/lib/python3.11'),Path(__file__).resolve().parents[2]/'src')
            if path.suffix in ('.py','.pyc','.so') and any(path.is_relative_to(root) for root in code_roots):
                return
            roots=(Path(os.environ['TINFO_ASSETS']).resolve(),Path('/usr/share/fonts'))
            if not any(path.is_relative_to(root) for root in roots):
                ATTEMPTS.append('application nonresource read '+str(path))
                raise AssertionError(ATTEMPTS[-1])

sys.addaudithook(audit)


@pytest.fixture(autouse=True)
def pure_execution(monkeypatch,request):
    import taiko_application.commands.prepared_score  # Complete imports before capability audit.
    from PIL import Image
    Image.init()
    import taiko_application.commands.score as score
    original=score.execute_score
    def execute(*args,**kwargs):
        global APPLICATION
        APPLICATION=True
        try:
            return original(*args,**kwargs)
        finally:
            APPLICATION=False
    monkeypatch.setattr(request.module,'execute_score',execute)
    monkeypatch.setattr(builtins,'__import__',guarded_import)
    yield
    assert not ATTEMPTS, ATTEMPTS[:3]
