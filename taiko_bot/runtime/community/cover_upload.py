"""Upload a saved cover and its bounded Viewer derivatives to OSS."""
from pathlib import Path
import os
import subprocess
from PIL import Image


def _upload_failure_reason(error: Exception) -> str:
    """Expose known error categories only; OSS output can contain credentials."""
    if isinstance(error, FileNotFoundError):
        return '服务器未安装 OSS 上传工具'
    if isinstance(error, subprocess.TimeoutExpired):
        return 'OSS 连接超时'
    if isinstance(error, subprocess.CalledProcessError):
        output = b'\n'.join(
            value.encode() if isinstance(value, str) else value
            for value in (error.stdout, error.stderr) if value
        )
        for code, reason in (
            (b'InvalidAccessKeyId', 'OSS 上传凭据无效，请联系管理员'),
            (b'SignatureDoesNotMatch', 'OSS 上传凭据校验失败，请联系管理员'),
            (b'AccessDenied', 'OSS 上传权限不足，请联系管理员'),
        ):
            if code in output:
                return reason
    return 'OSS 上传失败，请联系管理员'


def upload_cover(cover_path: Path):
    cover_path = Path(cover_path)
    if not cover_path.stem.isdecimal() or cover_path.suffix != '.png':
        return False, '封面文件无效'
    try:
        with Image.open(cover_path) as image:
            if image.format != 'PNG' or image.size != (400, 400):
                return False, '封面必须为 400×400 PNG'
            for size in (200, 400):
                target = cover_path.parent / 'thumb' / str(size) / (cover_path.stem + '.webp')
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(target.name + '.' + str(os.getpid()) + '.next')
                try:
                    with image.convert('RGB') as rgb, rgb.resize((size, size), Image.Resampling.LANCZOS) as thumb:
                        thumb.save(temp, format='WEBP', quality=85, method=4)
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
    except Exception:
        return False, '缩略图生成失败，请联系管理员'
    failed = []
    for path, key, media in [(cover_path, cover_path.name, 'image/png')] + [
        (cover_path.parent / 'thumb' / str(size) / (cover_path.stem + '.webp'),
         f'thumb/{size}/{cover_path.stem}.webp', 'image/webp') for size in (200, 400)
    ]:
        try:
            subprocess.run(['ossutil', 'cp', '-f', str(path), 'oss://sigaer/cover/' + key,
                            '--meta', 'Content-Type:' + media + '#Cache-Control:public, max-age=300'],
                           check=True, capture_output=True, timeout=40)
        except Exception as error:
            reason = _upload_failure_reason(error)
            if key == cover_path.name:
                return False, reason
            failed.append(reason)
    if not failed:
        return True, '原图及 200/400 缩略图已同步'
    return False, '原图已上传到 OSS；缩略图上传失败：' + failed[0]
