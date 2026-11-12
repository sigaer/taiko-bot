"""Fail the release gate on changed results, unbounded memory or wrong corpus."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixtures import verify
from report import load, validate

p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args()
assert verify(a.work/'fixture')['status']=='PASS'
before=load(a.work/'results','before');after=load(a.work/'results','after')
correctness=validate(before,after)
manifest=hashlib.sha256((a.work/'fixture/fixture-manifest.json').read_bytes()).hexdigest()
for data in [before,after]:
    for cohort,rows in data['cohorts'].items():
        if cohort!='handler':assert all(r['fixture_manifest_sha256']==manifest for r in rows),cohort
        assert all(r['environment']['versions']['Pillow']=='11.3.0' for r in rows)
        assert all(r['environment']['versions']['numpy']=='2.4.6' for r in rows)
        assert all(r['environment']['versions']['pandas']=='3.0.6' for r in rows)
        if cohort!='handler':
            assert all(r['environment']['limits']['cpu.max']=='200000 100000' and
                       r['environment']['limits']['memory.max']=='3221225472' for r in rows)

memory={}
for data in [before,after]:
    m=data['stress']['memory'];samples=[r['rss_kib'] for r in m['rss'] if 50<=r['iteration']<=100]
    # A stable periodic allocator may oscillate. Reject continuing monotone
    # growth above 8 MiB after fifty identical warm requests.
    continuing=all(b>=a-1024 for a,b in zip(samples,samples[1:])) and samples[-1]>samples[0]+8192
    assert not continuing,('sustained RSS growth',data['variant'],samples)
    requests=[r['wall_ns'] for r in m['requests'] if r['user']=='U05' and r['command']=='taikob30 v1'][:100]
    first,last=statistics.median(requests[:20]),statistics.median(requests[-20:])
    assert last<=first*1.3,('progressive slowdown',data['variant'],first,last)
    memory[data['variant']]=dict(late_rss_samples_kib=samples,first20_p50_ns=first,last20_p50_ns=last,
                                late_to_early_ratio=last/first,continuing_growth=continuing)
    assert len(m['faults'])==3 and all(r['closed'] for r in m['faults'])
    assert len(data['stress']['concurrency']['batches'])==40
    for mode in ['memory','concurrency']:
        assert data['stress'][mode]['status']=='PASS'
        if data['variant']=='after':assert data['stress'][mode]['executor_closed']
cache=after['stress']['memory']['cache'];assert cache['bytes']<=cache['limit']==64*1024**2
for mode in ['memory','concurrency']:
    mappings=[]
    for data in [before,after]:
        results=defaultdict(set)
        for row in data['stress'][mode]['requests']:
            results[(row['user'],row['command'])].add(json.dumps(row['output'],sort_keys=True))
        assert all(len(outputs)==1 for outputs in results.values())
        mappings.append(dict(results))
    assert mappings[0]==mappings[1],(mode,'stress result changed')
for user,command,n in [('U05','taikob30 v1',30),('U05','taikob',20)]:
    rows=[r for r in after['cohorts']['warm-query'] if r['user']==user and r['command']==command]
    assert len(rows)==20
    assert all(r['stages']['E.B30SingleRenderer._render']['calls']==n and
               r['stages'].get('E.encode.PNG',{}).get('calls',0)==0 for r in rows)
source=json.loads((a.work/'results/installed-source-parity.json').read_text());assert source['status']=='PASS' and len(source['files'])==401
result=dict(status='PASS',correctness=correctness,memory=memory,cache=cache,installed_source_files=len(source['files']))
(a.work/'results/acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
