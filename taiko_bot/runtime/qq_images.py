"""Shared official-QQ image policy: HTTPS Markdown, one send per reply."""
from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image

logger = logging.getLogger(__name__)


def write_public_image(directory: Path, filename: str, payload: bytes) -> None:
    """Publish a complete random-name image despite a private process umask."""
    if Path(filename).name != filename:
        raise ValueError("invalid cache filename")
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    directory.chmod(0o755)
    temporary = directory / ("." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(payload)
        os.replace(temporary, directory / filename)
    finally:
        temporary.unlink(missing_ok=True)


def authorize_image_publication(sender) -> None:
    """Private authorization must hold before publishing, as well as at send."""
    from .player.authority import AuthorizedDelivery

    if isinstance(sender, AuthorizedDelivery):
        sender._verify()


def build_qq_image_reply(event, image, *, text="", cache_image, prefix="taiko", keyboard=None):
    from nonebot.adapters.qq import Message, MessageSegment

    if hasattr(image, "seek"):
        image.seek(0)
    try:
        url = cache_image(image, prefix=prefix)
    except Exception as error:
        # This fallback occurs before any QQ request. Never retry/fallback here
        # after a network timeout or other uncertain delivery result.
        logger.warning("QQ Markdown cache unavailable; using media reply (%s)", type(error).__name__)
        message = Message()
        reference = str(getattr(event, "id", "") or "").strip()
        if reference:
            message += MessageSegment.reference(reference, ignore_error=True)
        if text:
            message += MessageSegment.text(str(text))
        if hasattr(image, "seek"):
            image.seek(0)
        message += MessageSegment.file_image(image)
        return message

    label = "img"
    try:
        source = image if isinstance(image, Path) else BytesIO(image if isinstance(image, bytes) else image.getvalue())
        with Image.open(source) as decoded:
            width, height = decoded.size
        label = f"img#{width}px #{height}px"
    except Exception:
        pass  # Preserve support for adapter-compatible payloads without dimensions.
    content = f"![{label}]({url})"
    if str(text or "").strip():
        content = str(text).strip() + "\n\n" + content
    message = Message(MessageSegment.markdown(content))
    if keyboard is not None:
        message += MessageSegment.keyboard(keyboard)
    return message
