from __future__ import annotations

import hashlib
from functools import lru_cache
import importlib.util
from io import BytesIO
from pathlib import Path
import random
import secrets
import subprocess
import time
from urllib.parse import urlsplit

from .config import Blocked


@lru_cache(maxsize=1)
def synthetic_jpeg() -> bytes:
    from PIL import Image, ImageDraw
    size = (1080, 2436)
    image = Image.frombytes("RGB", size, random.Random(20261113).randbytes(size[0] * size[1] * 3))
    draw = ImageDraw.Draw(image)
    for i in range(20):
        y = 130 + i * 110
        draw.rectangle((60, y, 1020, y + 45), fill=(245, 245, 245))
        draw.text((80, y + 10), f"SYNTHETIC QQ DELIVERY TEST / TILE {i:02d} / 0123456789", fill=(0, 0, 0))
    for quality in range(25, 96, 5):
        output = BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True)
        data = output.getvalue()
        if 500 * 1024 <= len(data) <= 800 * 1024:
            return data
    raise Blocked("synthetic_jpeg_size_out_of_range")


def image_payload(directory: Path) -> bytes:
    """Never accept a user image path; regenerate a fixed synthetic fixture."""
    data = synthetic_jpeg()
    target = directory / "synthetic.jpg"
    if target.is_symlink():
        raise Blocked("synthetic_image_symlink")
    if not target.exists() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(data).digest():
        with open(target, "wb", opener=lambda p, f: __import__('os').open(p, f, 0o600)) as file:
            file.write(data)
    return data


def cleanup_static(root: Path, ttl: int, *, now=None, all_generated=False) -> int:
    if not 300 <= ttl <= 1800 or root.name != "qq-delivery-probe" or root.is_symlink():
        raise Blocked("invalid_isolated_static_root")
    marker = root / ".synthetic-only"
    if not marker.is_file() or marker.read_text() != "qq-delivery-probe-v1\n":
        raise Blocked("isolated_static_marker_missing")
    now = time.time() if now is None else now
    count = 0
    for file in root.glob("probe-*.jpg"):
        if file.is_symlink() or not file.is_file():
            continue
        if all_generated or now - file.stat().st_mtime >= ttl:
            file.unlink(missing_ok=True)
            count += 1
    return count


class StaticImage:
    def __init__(self, config):
        self.config = config

    def prepare(self, data: bytes, state) -> tuple[str, bool]:
        c = self.config
        root = Path(c.static_root)
        parsed = urlsplit(c.static_base_url)
        if not (c.external_access_verified or c.external_probe_proxy):
            raise Blocked("external_access_confirmation_or_independent_proxy_required")
        if not c.domain_whitelisted and not (c.phase == "protocol" and c.domain_preflight_authorized):
            raise Blocked("domain_whitelist_or_single_protocol_trial_required")
        if not root.is_absolute() or root.name != "qq-delivery-probe" or root.is_symlink():
            raise Blocked("isolated_static_directory_required")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise Blocked("invalid_static_https_base")
        if not c.cleanup_timer_unit.startswith("taiko-qq-delivery-probe-") or not c.cleanup_timer_unit.endswith(".timer"):
            raise Blocked("invalid_cleanup_timer")
        # Fail closed until the independent persistent janitor is installed.
        result = subprocess.run(["systemctl", "is-active", "--quiet", c.cleanup_timer_unit], capture_output=True)
        if result.returncode:
            raise Blocked("automatic_static_cleanup_not_active")
        if not root.exists():
            root.mkdir(mode=0o755, parents=True)
            (root / ".synthetic-only").write_text("qq-delivery-probe-v1\n")
        marker = root / ".synthetic-only"
        if not marker.is_file() or marker.read_text() != "qq-delivery-probe-v1\n":
            raise Blocked("isolated_static_marker_missing")
        # QA intentionally uses umask 077. Only synthetic public assets get
        # readable permissions; private configuration/media state stay 0600.
        root.chmod(0o755)
        cleanup_static(root, c.static_ttl_seconds)
        entry = state.data.get("public_image")
        if entry and entry["expires_at"] > time.time() + 60 and (root / entry["filename"]).is_file():
            (root / entry["filename"]).chmod(0o644)
            return entry["url"], True
        # Load the installed existing cache implementation into an isolated module.
        # Its module globals are never changed in the production import namespace.
        import taiko_bot
        path = Path(taiko_bot.__file__).parent / "runtime/player/center/qq_markdown_media.py"
        spec = importlib.util.spec_from_file_location("_qq_delivery_synthetic_cache_" + secrets.token_hex(8), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.QQ_MARKDOWN_IMAGE_CACHE_DIR = root
        module.QQ_MARKDOWN_IMAGE_BASE_URL = c.static_base_url.rstrip("/")
        url = module.cache_markdown_image_url(data, prefix="probe")
        filename = urlsplit(url).path.rsplit("/", 1)[1]
        (root / filename).chmod(0o644)
        state.data["public_image"] = dict(filename=filename, url=url,
                                          expires_at=time.time() + c.static_ttl_seconds)
        state.save()
        return url, False

    async def verify(self, url: str, data: bytes) -> dict:
        import httpx
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False,
                                     proxy=self.config.external_probe_proxy or None) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200 or response.headers.get("content-type", "").split(";")[0] != "image/jpeg":
                    raise Blocked("static_https_status_or_content_type", http_status=response.status_code)
                parts = bytearray()
                async for chunk in response.aiter_bytes():
                    parts.extend(chunk)
                    if len(parts) > len(data):
                        raise Blocked("static_https_image_mismatch")
                if bytes(parts) != data:
                    raise Blocked("static_https_image_mismatch")
        return dict(static_verify_ms=round((time.perf_counter() - started) * 1000, 3),
                    external_verification="independent_proxy_fetch" if self.config.external_probe_proxy else "administrator_attested_plus_local_fetch", jpeg_verified=True)
