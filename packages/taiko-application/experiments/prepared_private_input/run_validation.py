"""Run via scripts/memory/run_qa.sh; requires installed Application 0.6.0, Pillow, pytest."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parent))
import pytest
from prepared_private_input import test_boundary as suite
from prepared_private_input.audit_imports import audit
from importlib.metadata import version
assert version('taiko-application')=='0.6.0'
result=pytest.main(['-q',str(root/'test_boundary.py'),'-p','no:cacheprovider'])
assert result==0,'Boundary tests failed'
report={'status':'PHASE_2F_D0_6_PREPARED_INPUT_VALIDATED','application':version('taiko-application'),
        'pillow':version('Pillow'),'parity_cases':suite.RECORDS,'import_graph':audit()}
child=subprocess.run([sys.executable,str(root/'runtime_audit.py')],capture_output=True,text=True,timeout=30,
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
assert child.returncode==0,child.stderr[-2000:]
report['runtime_audit']=json.loads(child.stdout)
# Installed command logic must be byte-identical to the frozen D0.5 checkout.
import taiko_application.commands.score as score
repo=root.parents[3]
expected=repo/'packages/taiko-application/src/taiko_application/commands/score.py'
assert Path(score.__file__).read_bytes()==expected.read_bytes()
report['execute_score_sha256']=hashlib.sha256(expected.read_bytes()).hexdigest()
changed=subprocess.check_output(['git','diff','8299f54','--name-only'],cwd=repo,text=True).splitlines()
assert all(name.startswith('packages/taiko-application/experiments/prepared_private_input/') or name == 'docs/prepared-private-input-prototype.md' for name in changed), 'Existing tracked source unexpectedly modified'
report['tracked_baseline_source_unchanged']=True
(a.output/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':report['status'],'parity_cases':len(suite.RECORDS),'import_modules':report['import_graph']['modules'],'runtime':report['runtime_audit']}))
