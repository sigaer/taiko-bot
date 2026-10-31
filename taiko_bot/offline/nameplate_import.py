"""Stage official nameplates from a mini-program archive without executing JS."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import urlopen

from PIL import Image

from .dress_import.package import DataParser, read_service

MODULE_MARKER = "!*** ./src/pages/components/title/data.ts ***!"


def parse_nameplate_assets(service: str) -> dict[str, str]:
    start = service.index(MODULE_MARKER) + len(MODULE_MARKER)
    end = service.find('},"./', start)
    module = service[start:end if end >= 0 else len(service)]
    match = re.search(r"\bvar\s+\w+\s*=\s*(\[)", module)
    if match is None:
        raise ValueError("Official title mapping missing")
    rows = DataParser(module[match.start(1):], {}, {}).value()
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise ValueError("Invalid title mapping size")
    assets: dict[str, str] = {}
    for row in rows:
        plate_id = row.get("id")
        if type(plate_id) is not int or not 0 <= plate_id <= 10000:
            raise ValueError("Invalid nameplate ID")
        for field, prefix in (("icon", "name_plate_"), ("dan_icon", "name_plate_dani_")):
            url = str(row.get(field) or "")
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.netloc != "taiko-file.gzheyoukeji.com":
                raise ValueError("Unexpected nameplate asset host")
            filename = f"{prefix}{plate_id}.png"
            if filename in assets:
                raise ValueError("Repeated nameplate ID")
            assets[filename] = url
    return assets


def validate_png(data: bytes) -> tuple[int, int]:
    if len(data) >= 2 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid or oversized nameplate PNG")
    with Image.open(BytesIO(data)) as image:
        if not 0 < image.width <= 4096 or not 0 < image.height <= 4096:
            raise ValueError("Invalid nameplate dimensions")
        image.load()
        return image.size


def download_assets(assets: dict[str, str], destination: Path) -> list[dict]:
    destination.mkdir(parents=True, exist_ok=True)
    by_url: dict[str, list[str]] = {}
    for filename, url in assets.items():
        if (destination / filename).exists():
            raise ValueError("Refusing to overwrite staged nameplates")
        by_url.setdefault(url, []).append(filename)

    def download(entry):
        url, filenames = entry
        with urlopen(url, timeout=20) as response:
            data = response.read(2 * 1024 * 1024)
        size = validate_png(data)
        for filename in filenames:
            (destination / filename).write_bytes(data)
        return {"files": filenames, "url": url, "size": size, "sha256": hashlib.sha256(data).hexdigest()}

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(download, by_url.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--missing-from", type=Path, help="Only stage files absent from this name_plate directory")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    assets = parse_nameplate_assets(read_service(args.archive))
    if args.missing_from:
        assets = {name: url for name, url in assets.items() if not (args.missing_from / name).exists()}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "nameplate-plan.json").write_text(json.dumps(assets, ensure_ascii=False, indent=2))
    if args.download:
        report = download_assets(assets, args.output / "name_plate")
        (args.output / "nameplate-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"plannedFiles": len(assets), "downloaded": args.download}))


if __name__ == "__main__":
    main()
