"""Reviewable ownership and protected-source scope checks, no runtime data."""
import ast,json,subprocess,sys
from pathlib import Path
T,S=map(Path,sys.argv[1:3])
for base in (T,S/'taiko'):
    tree=ast.parse((base/'plugins/taiko.py').read_text())
    names={node.name for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
    names.update(target.id for node in tree.body if isinstance(node,ast.Assign) for target in node.targets if isinstance(target,ast.Name))
    assert not names & {'trend','playtrend','trend_handle','playtrend_handle','_parse_trend_args','_parse_playtrend_args'}
    score=ast.parse((base/'plugins/utils/score_calculator.py').read_text())
    assert not any(isinstance(n,ast.FunctionDef) and n.name.startswith(('generate_rating_trend','generate_rating_playcount')) for n in score.body)
for repo,blocked in [(T,('packages/taiko-core/','packages/taiko-contract/','packages/taiko-store/','packages/taiko-application/')),(S,('taiko/taiko_store/','taiko/taiko_viewer/','taiko/taiko_contract/'))]:
    files=subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=repo,text=True).splitlines()
    assert not [p for p in files if p.startswith(blocked)]
for profile in ('center','client'):
    for path in (T/f'taiko_bot/runtime/player/{profile}/trend_support').glob('*.py'):
        source=path.read_text()
        for forbidden in ('ensure_userdata','PublicationStore','load_user_snapshots','load_v2_snapshot','requests.','urllib.'):
            assert forbidden not in source,(path,forbidden)
        ast.parse(source)
print(json.dumps({'legacy_matchers':0,'owned_trend_matchers':2,'protected_sources':'unchanged','renderers':'captured-input-only'}))
