"""Read-only, nonsecret production deployment evidence (no Bot events)."""
import argparse
import ast
import datetime
import json
from pathlib import Path
import re
import socket
import subprocess
import urllib.request

UNITS=['taiko-bot','taiko-public-api','taiko-sync-receiver','taiko-viewer','taiko-song-update','taiko-memory-monitor']


def snapshot():
    services={}
    for unit in UNITS:
        result=subprocess.run(['systemctl','show',unit+'.service','-p','MainPID','-p','ActiveState','-p','MemoryCurrent',
                               '-p','ExecMainStartTimestamp','-p','NRestarts'],text=True,capture_output=True,check=True)
        services[unit]=dict(line.split('=',1) for line in result.stdout.splitlines())
    pid=services['taiko-bot']['MainPID']
    journal=subprocess.run(['journalctl','_PID='+pid,'-n','5000','--no-pager','-o','cat'],text=True,capture_output=True,check=True).stdout
    inventory=None
    for line in journal.splitlines():
        if 'Taiko runtime inventory: ' in line:
            inventory=ast.literal_eval(re.sub(r'\x1b\[[0-9;]*m','',line.split('Taiko runtime inventory: ',1)[1]))
    with urllib.request.urlopen('http://127.0.0.1:37564/internal/bot-pool',timeout=5) as response:
        metrics=json.load(response)
    ports={}
    for port in (37563,37564):
        with socket.socket() as connection:
            connection.settimeout(1)
            ports[str(port)]=connection.connect_ex(('127.0.0.1',port))==0
    return dict(timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                release=str(Path('/opt/taiko-bot/current').resolve()),services=services,ports=ports,
                connected_bot_count=int(metrics['count']),actual_process_inventory=inventory)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    state=snapshot();a.output.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(state,ensure_ascii=False))
