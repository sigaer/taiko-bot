#!/usr/bin/env python3
"""Three targeted oracle tests; external pytest tooling, unchanged installed role."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--tests',type=Path,required=True)
parser.add_argument('--external-pytest',type=Path,required=True)
parser.add_argument('--frozen',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
assert sys.flags.isolated==1
assert not args.output.exists()
role_packages={d.metadata['Name'].lower().replace('_','-'):d.version for d in importlib.metadata.distributions()}
assert len(role_packages)==94
assert role_packages['taiko-bot']=='0.14.2'
assert role_packages['sakura-taiko-core']=='0.1.1'
assert role_packages['python-memory-runtime']=='1.1.0'
role_site=str(Path(sys.executable).parent.parent/'lib/python3.11/site-packages')
checkpoint=Path(role_site)/'taiko_bot/offline/growth-compatibility.dat'
checkpoint_before=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
# Append tooling only, after every existing isolated role path. Never install it
# into the 94-package role, and avoid parent conftest that injects source checkout.
sys.path.append(str(args.external_pytest))
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['TAIKO_COMPUTE_ONLY']='1'
os.environ['TAIKO_FROZEN_BASELINE_ROOT']=str(args.frozen)
import pytest
assert str(pytest.__file__).startswith(str(args.external_pytest)+'/')
selected=[str(args.tests/'test_frozen.py')+'::test_annual_success_cache_and_fingerprint',str(args.tests/'test_frozen.py')+'::test_annual_identity_oracle_changes_for_input_bytes_and_rejects_unapproved_domain',str(args.tests/'test_reappearance_revision.py')]
code=pytest.main(['--confcutdir='+str(args.tests),'-q','--runxfail','--tb=short',*selected])
modules={name:str(module.__file__) for name,module in sys.modules.items() if name.startswith(('taiko_bot','taiko_runtime','taiko_store','taiko_application','sakura_taiko_core','sakura_taiko_contract','runtime_memory')) and getattr(module,'__file__',None)}
assert modules and all(path.startswith(role_site+'/') for path in modules.values()),'Source fallback detected'
frozen={name:{'path':str(module.__file__),'sha256':hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()} for name,module in sys.modules.items() if name.startswith('frozen_source') and getattr(module,'__file__',None)}
assert frozen and all(x['path'].startswith(str(args.frozen)+'/') for x in frozen.values())
assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==checkpoint_before
evidence={'growthCompatibilitySha256':checkpoint_before,'status':'PASS' if code==0 else 'FAIL','exitCode':int(code),'tests':selected,'python':sys.executable,'isolated':sys.flags.isolated,'rolePackageCount':len(role_packages),'rolePackages':role_packages,'externalPytest':str(pytest.__file__),'productOrigins':modules,'frozenOrigins':frozen,'frozenDigestManifestSha256':hashlib.sha256((args.frozen/'source-digests.json').read_bytes()).hexdigest(),'testSourceSha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [args.tests/'test_frozen.py',args.tests/'test_reappearance_revision.py',args.tests/'test_version_summary.py']},'productionAccess':False,'growthCompatibilityModified':False}
args.output.write_text(json.dumps(evidence,indent=2)+'\n')
sys.exit(code)
