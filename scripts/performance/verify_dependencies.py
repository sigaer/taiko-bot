"""Verify installed dependency versions and payload bytes against production."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--before',type=Path,default=Path('/opt/taiko-bot/releases/0.21.1/lib/python3.11/site-packages'))
p.add_argument('--after',type=Path,default=Path('/opt/taiko-bot/releases/0.21.2/lib/python3.11/site-packages'))
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
def distributions(path):
    return {d.metadata['Name'].lower().replace('_','-'):d for d in metadata.distributions(path=[str(path)])}
before,after=distributions(a.before),distributions(a.after)
failures=[];verified=[]
for name,old in before.items():
    if name in ('taiko-bot','taiko-application'):continue
    new=after.get(name)
    if new is None or new.version!=old.version:
        failures.append(dict(package=name,before=old.version,after=new.version if new else None));continue
    count=0
    for relative in old.files or ():
        if any('.dist-info' in part or part=='__pycache__' for part in relative.parts):continue
        if relative.suffix=='.pyc' or '..' in relative.parts:continue
        left,right=old.locate_file(relative),new.locate_file(relative)
        if not left.is_file():continue
        if not right.is_file() or hashlib.sha256(left.read_bytes()).digest()!=hashlib.sha256(right.read_bytes()).digest():
            failures.append(dict(package=name,file=str(relative)))
        count+=1
    verified.append(dict(package=name,version=old.version,payload_files=count))
extra=set(after)-set(before)
if extra:failures.append(dict(unexpected_packages=sorted(extra)))
report=dict(status='PASS' if not failures else 'FAIL',verified=verified,failures=failures,
            changed_packages={n:dict(before=before[n].version,after=after[n].version) for n in ('taiko-bot','taiko-application')})
a.output.write_text(json.dumps(report,indent=2))
print(json.dumps(dict(status=report['status'],packages=len(verified),payload_files=sum(r['payload_files'] for r in verified),failures=failures[:10])))
assert not failures,'Installed dependencies differ from the production baseline'
