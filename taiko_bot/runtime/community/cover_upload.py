"""Publish one existing PNG and its bounded Viewer derivatives. Retry is safe."""
from pathlib import Path
import os
import subprocess
from PIL import Image


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
        return False, '缩略图生成失败；原图已保留，可用同一 cover 指令重试'
    failed = []
    for path, key, media in [(cover_path, cover_path.name, 'image/png')] + [
        (cover_path.parent / 'thumb' / str(size) / (cover_path.stem + '.webp'),
         f'thumb/{size}/{cover_path.stem}.webp', 'image/webp') for size in (200, 400)
    ]:
        try:
            subprocess.run(['ossutil', 'cp', '-f', str(path), 'oss://sigaer/cover/' + key,
                            '--meta', 'Content-Type:' + media + '#Cache-Control:public, max-age=300'],
                           check=True, capture_output=True, timeout=40)
        except Exception:
            failed.append(key)
    if not failed:
        return True, '原图及 200/400 缩略图已同步'
    original_ok = cover_path.name not in failed
    return False, ('原图已同步，缩略图未全部同步' if original_ok else '原图未同步') + '；请用同一 cover 指令重试'
