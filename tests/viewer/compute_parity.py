"""Successful full CLI DTO and publication-error parity using synthetic inputs.

Run with an installed wheel interpreter and the bounded QA runner. The frozen
source directory is produced by tests/offline/prepare_frozen.py (import changes
only); the Growth oracle below retains every calculation/projection statement.
"""
import argparse,copy,hashlib,json,os,runpy,shutil,subprocess,sys,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--sakura',type=Path,required=True);p.add_argument('--frozen',type=Path,required=True);p.add_argument('--taiko',type=Path,required=True)
a=p.parse_args();root=Path(tempfile.mkdtemp(prefix='viewer-compute-',dir='/var/tmp'))
try:
    songs=root/'songs';songs.mkdir();data=root/'userdata';data.mkdir()
    fixture=runpy.run_path(str(a.taiko/'packages/taiko-application/tests/fixture.py'))['FIXTURE']
    config=copy.deepcopy(fixture['rating_config']);base=next(iter(config['songs'].values()))
    roll=fixture['roll_catalog'][0];charts={};catalog=[];rolls=[];records=[]
    for i in range(80):
        sid=10000+i;title=f'Synthetic {i}'
        charts[str(sid)]={**base,'id':sid,'level':4,'title':title,'song_name':title}
        catalog.append(dict(id=sid,song_name=title,song_name_jp=title,level_4=9,shelf_status=0))
        rolls.append({**roll,'id':sid,'level':4,'title':title,'song_name':title})
        total=int(base.get('combo') or 600);good=int(total*.96)
        if i<30:records.append(dict(song_no=sid,level=4,good_cnt=good,ok_cnt=total-good-1,ng_cnt=1,high_score=900000,stage_cnt=1,clear_cnt=1,full_combo_cnt=0,dondaful_combo_cnt=0))
    config['songs']=charts
    for name,value in [('rating_structured_with_ids.json',config),('song_data.json',catalog),('song_data_raw.json',catalog),('song_alias.json',[]),('song_score.json',[]),('taiko_goku_onis.json',rolls),('taiko_goku_all_levels_stream.json',[])]:
        (songs/name).write_text(json.dumps(value))
    identity='114514';payload=dict(profile=dict(userid=identity,mydon_name='Synthetic'),songs=records)
    (data/(identity+'data.json')).write_text(json.dumps(payload))
    # Import-only adaptation of the exact requested Sakura baseline.
    text=subprocess.check_output(['git','-C',str(a.sakura),'show','86b8334:taiko/growth_compute/__main__.py'],text=True)
    begin=text.index('REPO_ROOT =');end=text.index('IMPORT_COMPLETE_AT =')
    text=text[:begin]+'from frozen_source import score_calculator as score\n'+text[end:]
    oracle=root/'oracle';oracle.mkdir();(oracle/'frozen_growth.py').write_text(text)
    env={**os.environ,'TAIKO_OFFLINE_ROOT':str(root),'TAIKO_CENTER_ROOT':str(root),'TAIKO_RUNTIME_ROOT':str(root),
        'TAIKO_USERDATA_DIR':str(data),'TAIKO_RUNTIME_ENV_FILE':str(root/'absent.env'),'MPLCONFIGDIR':str(root/'mpl'),
        'PYTHONDONTWRITEBYTECODE':'1','TAIKO_COMPUTE_ONLY':'1'}
    guard='''import os,sys,runpy
from pathlib import Path
def guard(event,args):
 if event in ('socket.connect','socket.getaddrinfo'):raise AssertionError('Network forbidden')
 if event=='open' and isinstance(args[0],(str,bytes)) and os.fsdecode(args[0]).startswith(('/home/sigaer/','/etc/taiko')):raise AssertionError('Production access forbidden')
sys.addaudithook(guard)
'''
    commands=[('recommendation_intelligence',['rating',identity]),('recommendation_intelligence',['ordinary',identity,'--basis','rating','--limit','3']),('recommendation_intelligence',['ordinary',identity,'--basis','stamina','--limit','3']),('recommendation_intelligence',['target',identity,'--target','full_combo','--limit','3']),('recommendation_intelligence',['target',identity,'--target','goku','--limit','3']),('growth_compute',['growth','--user',identity,'--limit','3'])]
    def cli(name,args,old=False):
        module=('frozen_growth' if name=='growth_compute' else 'frozen_source.'+name) if old else 'taiko_bot.offline.'+name
        code=guard
        if old:code+=f'sys.path[:0]={list(map(str,[oracle,a.frozen]))!r}\n'
        code+=f'sys.argv={[module,*args]!r}\nrunpy.run_module({module!r},run_name="__main__")'
        return subprocess.run([sys.executable,'-I','-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=45)
    expected=[]
    for name,args in commands:
        result=cli(name,args,True)
        assert result.returncode==0,result.stderr[-1500:]
        value=json.loads(result.stdout);value.pop('timing',None);expected.append(value)
    assert expected[0]['sampleCount']>20 and expected[1]['items'] and expected[3]['items']
    from taiko_store import PublicationStore
    store=PublicationStore(data,identity)
    with store.exclusive():store.commit({'current':json.dumps(payload).encode()})
    projection=data/(identity+'data.json')
    for stage in ('missing','tampered'):
        if stage=='missing':projection.unlink()
        else:projection.write_text('{"songs":[]}')
        for (name,args),value in zip(commands,expected):
            result=cli(name,args);assert result.returncode==0,result.stderr[-1500:]
            actual=json.loads(result.stdout);actual.pop('timing',None)
            assert actual==value,f'{name} {args[0]} full DTO mismatch'
    with store.shared():reference=store.view()['files']['current']
    (store.objects/reference['sha256']).write_bytes(b'corrupt')
    for name,args in commands:
        result=cli(name,args)
        assert result.returncode==75 and result.stderr.strip()=='Score publication is unavailable',(name,result.returncode,result.stderr[-500:])
    env['TAIKO_USERDATA_DIR']=str(root/'empty')
    result=cli(*commands[0]);assert result.returncode!=0 and 'FileNotFoundError' in result.stderr
    print('6 CLI successful full DTOs x 2 projection states + exact error/exit 75 + missing configured root: PASS')
finally:shutil.rmtree(root)
