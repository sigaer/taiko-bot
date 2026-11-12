"""Bounded synthetic B30 concurrency, RSS and exceptional lifecycle evidence."""
import argparse
import asyncio
import gc
import json
from pathlib import Path
import re
import resource
import sys
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmark import initialize, prepare_inputs, ports_for, output_digest, environment

p=argparse.ArgumentParser()
p.add_argument('--source',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True)
p.add_argument('--output',type=Path,required=True);p.add_argument('--mode',choices=['memory','concurrency','lifecycle'],required=True)
a=p.parse_args();a.profile='center';a.verify=False;a.artifacts={};a.scope='query'
mods=initialize(a)
from taiko_application.commands import CommandContext,CommandResult,prepare_b30,execute_b30
from taiko_application.score import B30SingleRenderer
from taiko_application.score.resources import RenderResources
new=(a.source/'taiko_bot/runtime/player/render_executor.py').exists()
if new:
    from taiko_bot.runtime.player.render_executor import RenderExecutor

pattern=re.compile(r'^/?taikob(?:\s*(50|[1-4]\d|[1-9]))?(?:\s*(.*))?$',re.I)
expected={}
report=dict(mode=a.mode,optimized=new,environment=environment(),requests=[],batches=[],rss=[],faults=[])


def rss():
    return next(int(line.split()[1]) for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmRSS:'))


async def main():
    pool=RenderExecutor(2) if new else None
    async def query(uid,command,submitted=None,record=True):
        started=submitted or time.perf_counter_ns()
        fixture=json.loads((a.fixture/'fixtures'/f'{uid}.json').read_text())
        ports=ports_for(a,mods,fixture,dict(history_snapshots=[],daily_points=[],observed_at='2026-11-11T12:00:00'))
        command_input=prepare_b30(CommandContext(match=pattern.match(command),profile='center'),ports)
        inputs=prepare_inputs(a,mods,fixture,command_input) if not isinstance(command_input,CommandResult) else {}
        ports=ports_for(a,mods,fixture,inputs)
        pure=lambda:command_input if isinstance(command_input,CommandResult) else execute_b30(CommandContext(user_id=10001,profile='center'),ports,command_input)
        result=await pool.run(pure) if pool else pure()
        elapsed=time.perf_counter_ns()-started
        digest=output_digest(result)
        key=uid,command
        if key in expected:assert digest==expected[key],('image changed',key)
        expected[key]=digest
        row=dict(user=uid,command=command,wall_ns=elapsed,output=digest,rss_kib=rss(),peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if record:report['requests'].append(row)
        return row
    await query('U05','taikob30 v1',record=False)
    await query('U05','taikob',record=False)
    if a.mode in ('memory','lifecycle'):
        gc.collect();report['rss'].append(dict(iteration=0,rss_kib=rss()))
        for i in range(100 if a.mode=='memory' else 0):
            await query('U05','taikob30 v1')
            if (i+1)%10==0:
                gc.collect();report['rss'].append(dict(iteration=i+1,rss_kib=rss()))
                print('repeated',i+1,report['rss'][-1],flush=True)
        for i in range(28 if a.mode=='memory' else 0):await query(f'U{i%14+1:02}','taikob' if i%2 else 'taikob30 v1')
        report['rss'].append(dict(iteration=128,rss_kib=rss()))
        # A real third-card failure must close every renderer-owned temporary.
        original_own=RenderResources._own;original_render=B30SingleRenderer._render
        for repeat in range(3):
            owned=[];calls=[0]
            def own(renderer,image):
                result=original_own(renderer,image)
                owned.append(image)
                return result
            def fail(renderer,*args,**kwargs):
                calls[0]+=1
                if calls[0]==3:raise ValueError('synthetic third-card fault')
                return original_render(renderer,*args,**kwargs)
            with patch.object(RenderResources,'_own',own),patch.object(B30SingleRenderer,'_render',fail):
                try:await query('U05','taikob30 v1')
                except ValueError as error:assert str(error)=='synthetic third-card fault'
                else:raise AssertionError('Fault did not reach actual renderer')
            for image in owned:
                try:image.getpixel((0,0))
                except ValueError:pass
                else:raise AssertionError('Renderer-owned image survived exceptional exit')
            report['faults'].append(dict(repeat=repeat,owned_images=len(owned),closed=True))
            await query('U05','taikob30 v1')
        try:
            from taiko_application.score.static_resources import STATIC_IMAGES
            report['cache']=dict(bytes=STATIC_IMAGES.bytes,limit=STATIC_IMAGES.max_bytes)
            assert STATIC_IMAGES.bytes<=STATIC_IMAGES.max_bytes
        except ImportError:report['cache']='baseline has no process image cache'
    else:
        for concurrency in (2,3):
            for iteration in range(20):
                running=[True];gaps=[]
                async def ticker():
                    previous=time.perf_counter_ns()
                    while running[0]:
                        await asyncio.sleep(.01)
                        now=time.perf_counter_ns();gaps.append(now-previous);previous=now
                monitor=asyncio.create_task(ticker());await asyncio.sleep(0)
                started=time.perf_counter_ns();cpu=time.process_time_ns()
                cases=[('U05','taikob30 v1'),('U05','taikob'),('U12','taikob')][:concurrency]
                requests=await asyncio.gather(*(query(uid,command,submitted=started) for uid,command in cases))
                wall=time.perf_counter_ns()-started;cpu=time.process_time_ns()-cpu
                running[0]=False;await monitor
                report['batches'].append(dict(concurrency=concurrency,iteration=iteration,wall_ns=wall,cpu_ns=cpu,
                    request_wall_ns=[r['wall_ns'] for r in requests],throughput_rps=concurrency*1e9/wall,
                    max_event_loop_gap_ns=max(gaps),rss_kib=rss()))
                if iteration%5==0:print('concurrency',concurrency,iteration,'seconds',round(wall/1e9,3),flush=True)
    if pool:
        await pool.shutdown()
        assert not pool._active and not pool._admitted
        # Reuse the same executor through multiple complete lifecycle cycles.
        for i in range(3):
            await pool.start();assert await pool.run(lambda:42)==42;await pool.shutdown()
        report['executor_closed']=True
    report['status']='PASS'

try:
    asyncio.run(main())
finally:
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(report.get('status','FAIL'),a.output,flush=True)
