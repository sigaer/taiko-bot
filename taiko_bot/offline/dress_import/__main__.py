"""Extract, normalize and stage official costume assets; never writes production."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import time
import threading
from urllib.parse import urlsplit

from PIL import Image
import requests

from .package import APPID, parse_catalog, read_service
from .corrections import correct_catalog

GROUPS = {
    'cosIconList': ('cos', 'cos'), 'headIconList': ('head', 'head'),
    'bodyIconList': ('body', 'body'), 'paintIconList': ('paint', 'paint'),
    'accessoriesIconList': ('accessories', 'accF'),
}
_LOCAL = threading.local()


def prepare(catalog):
    files = {}

    def add(path, url):
        if urlsplit(url).netloc != 'taiko-file.gzheyoukeji.com' or not url.endswith('.png'):
            raise ValueError(f"Unexpected resource URL {url}")
        if PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts:
            raise ValueError("Unsafe resource path")
        if path in files and files[path] != url:
            raise ValueError(f"Conflicting resource {path}")
        files[path] = url
        return path

    def localize(value):
        if isinstance(value, dict):
            return {key: localize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [localize(item) for item in value]
        if not isinstance(value, str) or not value.startswith('https://'):
            return value
        relative = value.split('/material/', 1)[1]
        if relative.startswith('dressup/290/common290/'):
            parts = relative.split('/')
            path = f'common/{parts[-2].removesuffix("_290")}/{parts[-1]}'
        elif relative.startswith('dressup/290/'):
            path = relative.removeprefix('dressup/290/').replace('acc/', 'accessories/', 1)
        elif relative.startswith('dressup/special/'):
            path = relative.removeprefix('dressup/')
        elif relative.startswith('suit/'):
            path = relative.replace('suit/', 'icons/', 1)
        else:
            path = f'special/{relative}'
        return add(path, value)

    # Normalize the main URL before walking nested rules, so aliases use game IDs.
    normalized = dict(catalog)
    for group, (directory, prefix) in GROUPS.items():
        normalized[group] = []
        for original in catalog[group]:
            entry = dict(original)
            url = entry.pop('url')
            entry = localize(entry)
            entry['url'] = add(f'{directory}/{prefix}_290_{original["id"]:03}.png', url) if url else ''
            normalized[group].append(entry)
    for key in catalog.keys() - GROUPS.keys():
        normalized[key] = localize(catalog[key])
    return normalized, files


def download(path, url, root, cache):
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    cached = cache / hashlib.sha256(url.encode()).hexdigest()
    for attempt in range(3):
        try:
            if cached.exists():
                data = cached.read_bytes()
            else:
                if not hasattr(_LOCAL, 'session'):
                    _LOCAL.session = requests.Session()
                response = _LOCAL.session.get(url, timeout=(10, 30))
                response.raise_for_status()
                data = response.content
            if len(data) > 8 * 1024 * 1024:
                raise ValueError('Image too large')
            with Image.open(BytesIO(data)) as image:
                if image.format != 'PNG' or max(image.size) > 2048:
                    raise ValueError('Invalid costume image')
                size = image.size
                image.verify()
            if not cached.exists():
                temporary = cached.with_suffix(f'.{hashlib.sha256(path.encode()).hexdigest()[:12]}.tmp')
                temporary.write_bytes(data)
                temporary.replace(cached)
            temporary = destination.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(destination)
            return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'size': size}
        except (requests.RequestException, OSError, ValueError) as error:
            if attempt == 2:
                return {'path': path, 'url': url, 'error': str(error)}
            time.sleep(attempt + 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('output', type=Path, help='New staging directory; not production assets/dress')
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    if args.output.resolve() == Path('/home/sigaer/taiko/assets/dress'):
        parser.error('Use staging, then verify before publishing')
    args.output.mkdir(parents=True, exist_ok=True)
    catalog, files = prepare(correct_catalog(parse_catalog(read_service(args.archive))))
    catalog['source'] = {'appid': APPID, 'archiveSha256': hashlib.sha256(args.archive.read_bytes()).hexdigest()}
    (args.output / 'catalog.pending.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
    (args.output / 'download-plan.json').write_text(json.dumps(files, indent=2))
    print(json.dumps({'groups': {name: len(catalog[name]) for name in GROUPS}, 'files': len(files)}), flush=True)
    if not args.download:
        return
    cache = args.output / '.download-cache'
    cache.mkdir(exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, path, url, args.output / 'dress', cache) for path, url in files.items()]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if 'error' in result:
                print(json.dumps(result), flush=True)
            if len(results) % 250 == 0:
                print(f'Downloaded {len(results)}/{len(files)}', flush=True)
    (args.output / 'download-report.json').write_text(json.dumps(results, indent=2))
    failed = sum('error' in result for result in results)
    if failed:
        raise SystemExit(f'{failed} resources failed; catalog was not published')
    (args.output / 'dress' / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')))
    print(f'Validated {len(results)} assets', flush=True)


if __name__ == '__main__':
    main()
