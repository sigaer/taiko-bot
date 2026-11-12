"""Serial benchmark cohorts, each invocation bounded by the workspace QA runner."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from benchmark import MAIN,CENTER,CLIENT

p=argparse.ArgumentParser()
p.add_argument('--source',type=Path,required=True)
p.add_argument('--fixture',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--cohort',required=True,choices=['smoke','warm-query','warm-compute','warm-draw','cold','matrix-center','matrix-client','edges-center','edges-client','local'])
a=p.parse_args()
assert os.environ.get('QA_RUN_ID'), 'Use the existing memory QA wrapper'
a.output.parent.mkdir(parents=True,exist_ok=True)
base=[sys.executable,str(Path(__file__).with_name('benchmark.py')),'--source',str(a.source),
      '--fixture',str(a.fixture),'--output',str(a.output)]
if a.cohort.startswith('warm-'):
    subprocess.run(base+['--scope',a.cohort[5:]],check=True)
elif a.cohort=='cold':
    for case in MAIN:
        for i in range(5):
            temporary=Path(os.environ['QA_RUN_TMPDIR'])/'cold-raw.jsonl'
            temporary.unlink(missing_ok=True)
            started=time.perf_counter_ns()
            subprocess.run(base+['--output',str(temporary),'--scope','query','--cases',json.dumps([case]),'--warmup','0','--repeats','1'],check=True)
            elapsed=time.perf_counter_ns()-started
            with a.output.open('a') as output:
                for line in temporary.read_text().splitlines():
                    row=json.loads(line);row['process_wall_ns']=elapsed
                    output.write(json.dumps(row,ensure_ascii=False)+'\n')
elif a.cohort.startswith('matrix-'):
    profile=a.cohort[7:]
    for i in range(1,15):
        subprocess.run(base+['--profile',profile,'--cases',json.dumps([(f'U{i:02}',c) for c in (CENTER if profile=='center' else CLIENT)]),
                              '--warmup','0','--repeats','1','--verify'],check=True)
elif a.cohort.startswith('edges-'):
    profile=a.cohort[6:]
    commands=(['taikob1 v1','taikob2 v1','taikob19 v1','taikob29 v2','taikob49 v2','taikob0','taikob51',
               'taikob20 v2 --dim=手速','taikob20 v2 -d 爆发','taikob20 v2 【节奏】','taikob20 v2 复合',
               'taikob20 v1 大歌','taikob20 v1 体力','taikob20 v1 高速','taikob20 v1 复合',
               'taikob20 v1 -r','taikob20 v2 --dim','taikob20 v3','taikob20 v1 v1'] if profile=='center' else
              ['taikob','taikob1','taikob19','taikob49','taikob20 v2 手速','taikob20 v2 爆发',
               'taikob20 v2 节奏','taikob20 v2 复合','taikob20 v2 综合','taikob20 v2 -r','taikob20 v2 --dim'])
    cases=[('U05',c) for c in commands]
    for uid in ('E01','E02','E03'):
        cases += [(uid,c) for c in (['taikob','taikob30 v1','taikob20 v2 精度'] if profile=='center' else ['taikob30','taikob20 v2','taikob20 v2 精度'])]
    subprocess.run(base+['--profile',profile,'--cases',json.dumps(cases),
                        '--warmup','0','--repeats','1','--verify'],check=True)
else:
    subprocess.run(base+['--cases',json.dumps(MAIN if a.cohort=='local' else MAIN[:1]),'--warmup','0','--repeats','1'],check=True)
