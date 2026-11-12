"""Run B30 regression units with pinned products and external pytest tooling."""
import argparse
from pathlib import Path
import os
import sys
import importlib
sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmark import initialize

p=argparse.ArgumentParser()
p.add_argument('--source',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True)
p.add_argument('--tests',nargs='+',required=True)
p.add_argument('--profile',choices=['center','client'],default='center')
a=p.parse_args()
assert os.environ.get('QA_RUN_ID'), 'Use the workspace memory runner'
mods=initialize(a)
if a.profile=='center':importlib.reload(mods['data'])
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
sys.path.append('/usr/lib/python3.11/site-packages')
import pytest
raise SystemExit(pytest.main(['-q','--tb=short','--basetemp',str(Path(os.environ['QA_RUN_TMPDIR'])/'pytest'),
                             '-o','cache_dir='+str(Path(os.environ['QA_RUN_TMPDIR'])/'pytest-cache'),*a.tests]))
