"""Verified OurTaiko resource downloads, separate from the maintained ESE checkout."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import requests

SOURCE_NAME = "ourtaiko"


def resource_root(runtime_root):
    return Path(runtime_root) / "assets/catalog_sources/ourtaiko"


def catalog_resource_root(song, ese_root, *, runtime_root=None):
    if song.get("resource_source") == SOURCE_NAME:
        if runtime_root is None:
            from .paths import root
            runtime_root = root()
        return resource_root(runtime_root)
    return Path(ese_root)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(descriptor, destination, *, maximum, session):
    digest, size, url = descriptor["sha256"], descriptor["size"], descriptor["url"]
    parsed = urlsplit(url)
    if (not re.fullmatch(r"[a-f0-9]{64}", digest) or type(size) is not int or not 0 < size <= maximum
            or parsed.scheme != "https" or parsed.netloc != "distrib.ourtaiko.org"
            or parsed.username or parsed.password
            or not re.fullmatch(r"/database/" + digest + r"\.[a-z0-9]+", parsed.path)):
        raise ValueError("Invalid OurTaiko resource manifest")
    path = Path(destination)
    if path.is_file() and path.stat().st_size == size and file_hash(path) == digest:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".download-", dir=path.parent)
    try:
        observed, hashed = 0, hashlib.sha256()
        with os.fdopen(fd, "wb") as output:
            with session.get(url, stream=True, timeout=(10, 30), allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("Unexpected OurTaiko download response")
                for block in response.iter_content(65536):
                    observed += len(block)
                    if observed > size or observed > maximum:
                        raise ValueError("OurTaiko resource size exceeded")
                    output.write(block); hashed.update(block)
            if observed != size or hashed.hexdigest() != digest:
                raise ValueError("OurTaiko resource integrity mismatch")
            output.flush(); os.fsync(output.fileno()); os.fchmod(output.fileno(), 0o644)
        os.replace(temporary, path)
        return path
    finally:
        Path(temporary).unlink(missing_ok=True)


def download_chart_resources(chart, runtime_root):
    source = chart["id"]
    if not re.fullmatch(r"[a-f0-9]{32}", source):
        raise ValueError("Invalid OurTaiko source ID")
    if not chart.get("hasFiles"):
        raise ValueError("OurTaiko has no resource files")
    with requests.Session() as session:
        response = session.get(f"https://database.ourtaiko.org/api/v1/charts/{source}/resources", timeout=(10, 30))
        response.raise_for_status()
        payload = response.json()
        if payload.get("chartId") != source:
            raise ValueError("OurTaiko resource identity mismatch")
        resources = payload["resources"]
        directory = resource_root(runtime_root) / source
        tja = resources["tja"]
        tja_path = download_file(tja, directory / (tja["sha256"] + ".tja"), maximum=2 * 1024**2, session=session)
        from .tja_roll_parser import read_tja_text
        from .catalog_resources import single_levels
        from .ourtaiko_catalog import chart_levels
        text = read_tja_text(str(tja_path))
        levels = single_levels(text)
        if any(levels.get(course) != level for course, level in chart_levels(chart).items()):
            raise ValueError("OurTaiko chart course identity mismatch")
        wave = re.search(r"^\s*WAVE\s*:(.+?)\s*$", text, re.M | re.I)
        if not wave or wave.group(1) in (".", "..") or "\0" in wave.group(1) or Path(wave.group(1)).name != wave.group(1) or "\\" in wave.group(1):
            raise ValueError("Unsafe or missing OurTaiko WAVE filename")
        audio = resources["audio"]
        suffix = Path(urlsplit(audio["url"]).path).suffix.lower()
        if suffix not in (".ogg", ".mp3", ".wav"):
            raise ValueError("Unsupported OurTaiko audio resource")
        audio_path = download_file(audio, directory / wave.group(1), maximum=32 * 1024**2, session=session)
        return {"resource_source": SOURCE_NAME,
                "tja_path": tja_path.relative_to(resource_root(runtime_root)).as_posix(),
                "audio_path": audio_path.relative_to(resource_root(runtime_root)).as_posix(),
                "tja_sha256": tja["sha256"], "audio_sha256": audio["sha256"]}
