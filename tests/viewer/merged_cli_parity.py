"""Installed merged-read worker protocol versus the exact retired CLI wrapper."""
import argparse,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
from taiko_store import PublicationStore
p=argparse.ArgumentParser();p.add_argument('--sakura',type=Path,required=True);a=p.parse_args()
root=Path(tempfile.mkdtemp(prefix='merged-wheel-',dir='/var/tmp'))
try:
    (root/'songs').mkdir();(root/'songs/song_data.json').write_text('[{"id":7,"max_combo":[0,0,0,100,0]}]')
    data=root/'userdata'
    stores=[]
    for identity,score in [('111',800000),('222',900000)]:
        payload=dict(profile={'mydon_name':identity},achievement={},songs=[dict(song_no=7,level=4,high_score=score,good_cnt=90,ok_cnt=10,stage_cnt=3)])
        store=PublicationStore(data,identity)
        with store.exclusive():store.commit({'current':json.dumps(payload).encode()})
        stores.append(store)
    old=root/'frozen_worker.py';old.write_bytes(subprocess.check_output(['git','-C',str(a.sakura),'show','86b8334:taiko/scripts/merged_read_cli.py']))
    env={**os.environ,'TAIKO_CENTER_ROOT':str(root),'TAIKO_RUNTIME_ROOT':str(root),'TAIKO_RUNTIME_ENV_FILE':str(root/'absent.env')}
    guard="""import sys,os,runpy
 def_unused=0
""".replace(' def_unused=0','def guard(event,args):\n if event in (\'socket.connect\',\'socket.getaddrinfo\'):raise AssertionError(\'network\')\n if event==\'open\' and isinstance(args[0],(str,bytes)) and os.fsdecode(args[0]).startswith((\'/home/sigaer/\',\'/etc/taiko\')):raise AssertionError(\'private input\')\nsys.addaudithook(guard)')
    def run(messages,frozen):
        launch=f'runpy.run_path({str(old)!r},run_name="__main__")' if frozen else 'runpy.run_module("taiko_bot.cli.merged_read_cli",run_name="__main__")'
        result=subprocess.run([sys.executable,'-I','-c',guard+launch],input=''.join(json.dumps(x)+'\n' for x in messages),text=True,capture_output=True,env=env,cwd=root,timeout=10)
        assert result.returncode==0,result.stderr[-1000:]
        return [json.loads(x) for x in result.stdout.splitlines()]
    for kind in ('current','history'):
        request=dict(root=str(data),sources=['111','222'],profileSource='111',kind=kind)
        messages=[request,{'method':'derive'},{'method':'finish'}]
        expected=run(messages,True);actual=run(messages,False)
        assert expected[0]['ready'] and expected[1]['ok'] and expected[2]=={'finished':True}
        assert actual==expected
        if kind=='current':assert actual[1]['payload']['songs'][0]['high_score']==900000
    invalid=[dict(root=str(data),sources=['111','111'])]
    assert run(invalid,False)==run(invalid,True)==[{'error':'merged_unavailable'}]
    for store in stores:
        with store.exclusive():pass
    print('Merged current/history protocol, source vector, invalid-source error and lease release: PASS')
finally:shutil.rmtree(root)
