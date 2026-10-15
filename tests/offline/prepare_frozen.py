"""Prepare import-only frozen adapters from an exact Sakura commit, outside the checkout.

Usage: python prepare_frozen.py SAKURA_GIT OUTPUT_DIRECTORY
Only tracked utility code/reference JSON is read. Player data, environment files,
comment-only historical credential snippets and the eager host initializer are excluded.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    revision='790c2c7'
    def git(*arguments):
        return subprocess.check_output(['git','-C',str(args.repository),*arguments])
    names=git('ls-tree','-r','--name-only',revision,'taiko/plugins/utils').decode().splitlines()
    output=args.destination/'frozen_source';output.mkdir(parents=True,exist_ok=True)
    digests={}
    for name in names:
        relative=Path(name).relative_to('taiko/plugins/utils')
        if relative.name in {'update_db.py','generate_alias.py','standalone.py'} or relative.suffix not in {'.py','.json'}:
            continue
        raw=git('show',f'{revision}:{name}');digests[name]=hashlib.sha256(raw).hexdigest()
        target=output/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if relative.suffix=='.json':target.write_bytes(raw);continue
        if relative==Path('__init__.py'):target.write_text('');continue
        text=raw.decode().replace('plugins.utils','frozen_source')
        text=text.replace('from taiko_runtime.memory import','from taiko_bot.offline.memory import').replace('from taiko_runtime.runtime_env import','from taiko_bot.runtime.player.center.runtime_env import')
        text=re.sub(r'(["\'])/home/sigaer/taiko(?:/([^"\']*))?\1',lambda m:'str(_runtime_root()'+(' / '+repr(m[2]) if m[2] else '')+')',text)
        if '_runtime_root()' in text:
            nodes=ast.parse(text).body
            position=next((n.end_lineno for n in nodes if isinstance(n,ast.ImportFrom) and n.module=='__future__'),0)
            lines=text.splitlines(keepends=True);lines.insert(position,'from taiko_bot.offline.paths import root as _runtime_root\n');text=''.join(lines)
        target.write_text(text)
    (args.destination/'tjaAnalyzer.py').write_bytes(git('show',f'{revision}:taiko/tjaAnalyzer.py'))
    (args.destination/'source-digests.json').write_text(json.dumps(digests,indent=2)+'\n')

if __name__=='__main__':main()
