"""Content identity for installed algorithms, independent of install location.

No timestamps or package version alone stand in for algorithm contents. This
command imports no algorithm modules (which can eagerly load runtime data).
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def installed_inputs():
    roots = {}
    for name in ('taiko_bot', 'taiko_application', 'sakura_taiko_core', 'taiko_store'):
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError(f'Required installed package unavailable: {name}')
        roots[name] = Path(next(iter(spec.submodule_search_locations)))
    files = {}
    for name, root in roots.items():
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.json') and '__pycache__' not in path.parts:
                files[f'{name}/{path.relative_to(root).as_posix()}'] = path
    return files


def artifact_identity(files=None):
    digest = hashlib.sha256(b'taiko-installed-algorithms-v1\0')
    for name, path in sorted((files or installed_inputs()).items()):
        digest.update(name.encode()); digest.update(b'\0')
        with path.open('rb') as source:
            while chunk := source.read(65536):
                digest.update(chunk)
        digest.update(b'\0')
    return digest.hexdigest()


def manifest():
    root = Path(__file__).parent
    return dict(protocol=1, identity=artifact_identity(), annualRoot=str(root/'annual_summary'),
                schemaPath=str(root/'schemas/annual-summary-v4.schema.json'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--growth-root', type=Path)
    args = parser.parse_args()
    print(growth_revision(args.growth_root) if args.growth_root else json.dumps(manifest(), separators=(',', ':')))


def growth_revision(data_root):
    """Retain the last complete legacy model identity only for exact wheel inputs.

    The compatibility checkpoint is a hash prefix, never executable legacy code.
    A changed installed input takes the v2 path; old measurements are immutable.
    """
    from ._sha256_checkpoint import NativeContinuation
    identity = artifact_identity()
    compatibility = json.loads((Path(__file__).parent/'growth-compatibility.dat').read_text())
    if identity == compatibility['artifactIdentity']:
        digest = NativeContinuation(compatibility['checkpoint'])
    else:
        digest = hashlib.sha256(('taiko-growth-revision-v2\0'+identity+'\0').encode())
    for label in ('songs/rating_structured_with_ids.json', 'songs/song_data.json', 'songs/song_alias.json'):
        digest.update(label.encode()); digest.update(b'\0')
        with (Path(data_root)/label).open('rb') as source:
            while chunk := source.read(65536):
                digest.update(chunk)
        digest.update(b'\0')
    return digest.hexdigest()


if __name__ == '__main__':
    main()
