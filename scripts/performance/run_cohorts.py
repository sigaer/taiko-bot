"""Coordinate separate bounded QA units; no workload runs in this supervisor."""
import argparse
from pathlib import Path
import subprocess
import sys
import time

p=argparse.ArgumentParser()
p.add_argument('--source',type=Path,required=True)
p.add_argument('--fixture',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--prefix',required=True)
p.add_argument('--cohorts',nargs='+',default=['warm-query','warm-compute','warm-draw','cold','matrix-center','matrix-client'])
a=p.parse_args()
runner='/home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh'
for cohort in a.cohorts:
    output=a.output/f'{a.prefix}-{cohort}.jsonl'
    if output.exists():raise SystemExit('Refusing to append to an earlier cohort: '+str(output))
    command=['bash',runner,sys.executable,str(Path(__file__).with_name('suite.py')),
             '--source',str(a.source),'--fixture',str(a.fixture),'--output',str(output),'--cohort',cohort]
    while True:
        result=subprocess.run(command)
        if result.returncode!=75:break
        time.sleep(10)
    if result.returncode:raise SystemExit(result.returncode)
    print('Completed',a.prefix,cohort,flush=True)
