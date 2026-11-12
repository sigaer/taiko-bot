"""Optional static mirrors must not block the authoritative Viewer catalog."""
import logging
import subprocess


def sync_public_mirror(source, destination):
    try:
        subprocess.run(['ossutil', 'cp', '-f', str(source), destination], check=True,
                       capture_output=True, text=True, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError) as error:
        logging.getLogger(__name__).warning('静态镜像未更新，中心曲库继续发布: %s (%s)', source, type(error).__name__)
        return False
