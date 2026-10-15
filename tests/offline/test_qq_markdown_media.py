import asyncio, os, time
from io import BytesIO
from PIL import Image
from taiko_bot.runtime import center_markdown_media as qq_markdown_media
def _build_png_bytes() -> bytes:
    img = Image.new("RGB", (4, 4), (255, 0, 0))
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()

def test_cache_markdown_image_url_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        qq_markdown_media,
        "QQ_MARKDOWN_IMAGE_CACHE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        qq_markdown_media,
        "QQ_MARKDOWN_IMAGE_BASE_URL",
        "https://viewer.sakura-bot.cn/qqbot-cache/taiko",
    )

    image_bytes = _build_png_bytes()
    image_url = qq_markdown_media.cache_markdown_image_url(
        image_bytes,
        prefix="taikoupdate",
    )

    assert image_url.startswith("https://viewer.sakura-bot.cn/qqbot-cache/taiko/")
    created_files = list(tmp_path.iterdir())
    assert len(created_files) == 1
    assert created_files[0].suffix == ".png"

    expired = tmp_path / "expired.png"
    expired.write_bytes(image_bytes)
    expired_ts = time.time() - qq_markdown_media.QQ_MARKDOWN_IMAGE_TTL_SECONDS - 5
    os.utime(expired, (expired_ts, expired_ts))

    deleted = qq_markdown_media.cleanup_expired_markdown_images(now=time.time())

    assert deleted >= 1
    assert not expired.exists()
