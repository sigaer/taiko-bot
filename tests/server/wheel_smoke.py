"""Run with the installed venv's python -I, outside either checkout."""
import hashlib
import http.client
import importlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

with tempfile.TemporaryDirectory(prefix="taiko-wheel-service-",dir="/var/tmp") as directory:
    root=Path(directory);(root/"songs").mkdir()
    (root/"songs/song_data.json").write_text('[{"id":1,"song_name":"Synthetic"}]')
    (root/"songs/song_alias.json").write_text('[{"id":1,"aliases":["test"]}]')
    (root/"songs/grade_dojo_nijiiro_2025_simple.json").write_text('{"grades":[]}')
    environment=os.environ.copy()
    for key,value in {"TAIKO_RUNTIME_ROOT":directory,"TAIKO_CENTER_ROOT":directory,"TAIKO_RUNTIME_ENV_FILE":str(root/"none.env"),
        "TAIKO_USERDATA_DIR":str(root/"userdata"),"TAIKO_ACCOUNT_CACHE_DIR":str(root/"cache"),"TAIKO_HIROBA_TOKEN_DIR":str(root/"tokens"),
        "TAIKO_HIROBA_COOLDOWN_PATH":str(root/"cooldown.json"),"TAIKO_WAHLAP_CONFIG_PATH":str(root/"config.json"),
        "TAIKO_DB_USER":"synthetic","TAIKO_DB_PASSWORD":"synthetic","TAIKO_DB_NAME":"service_test","HIROBA_CRED_KEY":"synthetic"}.items():environment[key]=value
    environment.pop("PYTHONPATH",None)
    os.environ.update(environment)
    os.chdir(root)
    guard_source='''
import os,sys

def guard(event,args):
    if event=="open" and isinstance(args[0],(str,bytes)):
        p=os.fsdecode(args[0])
        if p.startswith(("/home/sigaer/taiko/","/home/sigaer/git/","/etc/taiko")):
            raise AssertionError("production files forbidden")
    if event in {"socket.connect","socket.getaddrinfo"}:
        raise AssertionError("outbound network forbidden in installed CLI/startup smoke")
sys.addaudithook(guard)
'''
    exec(guard_source)
    for name in ["taiko_bot.services.public_api","taiko_bot.services.sync_dispatch_server","taiko_bot.cli.source_mutation_cli",
        "taiko_bot.cli.account_sync_cli","taiko_bot.cli.qq_migration_cli","taiko_bot.cli.hiroba_credential_cli","taiko_bot.cli.sync_hiroba",
        "taiko_bot.runtime.player.center.daily_ability","taiko_bot.runtime.player.center.taikob_v2"]:
        module=importlib.import_module(name)
        assert "site-packages" in module.__file__, module.__file__
    assert "plugins.utils" not in sys.modules and "taiko_bot.runtime.public" not in sys.modules
    # Controller HTTP only connects to ephemeral owned loopback ports. Child rejects every outbound connection.
    # Parent guard installed above blocks connect, so use a short separate isolated controller.
    controller='''import http.client,json,sys
c=http.client.HTTPConnection("127.0.0.1",int(sys.argv[1]),timeout=2)
try:
 c.request("GET",sys.argv[2]);r=c.getresponse();print(json.dumps([r.status,json.loads(r.read())]))
finally:c.close()
'''
    for module,path,expected in [("taiko_bot.services.public_api","/api/song_data",200),("taiko_bot.services.sync_dispatch_server","/health",200)]:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1",0));port=listener.getsockname()[1]
        env=environment|{"TAIKO_SYNC_RECEIVER_PORT":str(port),"TAIKO_SYNC_RECEIVER_HOST":"127.0.0.1"}
        args=["--host","127.0.0.1","--port",str(port)] if module.endswith("public_api") else []
        code=guard_source+'\nimport runpy\nsys.argv='+repr([module,*args])+'\nrunpy.run_module('+repr(module)+',run_name="__main__")'
        with (root/(module.rsplit('.',1)[-1]+'.log')).open('w') as log:
            process=subprocess.Popen([sys.executable,"-I","-c",code],env=env,stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+10
                while True:
                    result=subprocess.run([sys.executable,"-I","-c",controller,str(port),path],capture_output=True,text=True,timeout=3)
                    if result.returncode==0:break
                    assert process.poll() is None and time.monotonic()<deadline,"installed server failed to start"
                    time.sleep(.1)
                assert json.loads(result.stdout)[0]==expected
            finally:
                if process.poll() is None:process.send_signal(signal.SIGINT)
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait();raise
            assert process.returncode==0
    for name,payload,code in [("source_mutation_cli",'{',"invalid_request"),("account_sync_cli",'{',"invalid_request"),("qq_migration_cli",'{',"invalid_request"),
        ("hiroba_credential_cli",json.dumps({"mode":"fingerprint","operationId":"a"*32,"email":"test@example.test","password":"synthetic","target":"","principal":"onebot_v11:1"}),None)]:
        command=guard_source+'\nimport runpy\nrunpy.run_module("taiko_bot.cli.'+name+'",run_name="__main__")'
        result=subprocess.run([sys.executable,"-I","-c",command],env=environment,input=payload,capture_output=True,text=True,timeout=10,check=True)
        response=json.loads(result.stdout)
        assert response.get("error")==code
        if code is None:assert response["ok"] and len(response["result"]["intentHash"])==64
    result=subprocess.run([sys.executable,"-I","-m","taiko_bot.cli.sync_hiroba","--help"],env=environment,capture_output=True,text=True,timeout=10,check=True)
    assert "--dry-run" in result.stdout
    print("installed wheel: 9 imports, 2 real service startups/HTTP, 5 CLI checks PASS; no Sakura path, Bot registration or outbound network")
