import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('prune_releases', Path(__file__).resolve().parents[1] / 'scripts/prune_releases.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def installation(tmp_path):
    for version in ('0.18.1', '0.25.5', '0.25.6', '0.25.7', '0.25.8'):
        folder = tmp_path / 'releases' / version
        folder.mkdir(parents=True)
        (folder / 'installed').write_text('fixture')
    (tmp_path / 'current').symlink_to(tmp_path / 'releases/0.25.7')
    return tmp_path


def test_delete_old_releases_but_keep_referenced_current_and_future(tmp_path):
    root = installation(tmp_path)
    report = cleanup.prune('0.25.7', root=root, apply=True, scan=lambda root: {'0.18.1'})
    assert report['removed'] == ['0.25.5', '0.25.6']
    assert {p.name for p in (root / 'releases').iterdir()} == {'0.18.1', '0.25.7', '0.25.8'}


def test_consumer_appearing_on_recheck_is_preserved(tmp_path):
    root = installation(tmp_path)
    calls = iter([set(), {'0.25.6'}])
    report = cleanup.prune('0.25.7', root=root, apply=True, scan=lambda root: next(calls))
    assert '0.25.6' not in report['removed']
    assert (root / 'releases/0.25.6').exists()


def test_inspection_failure_deletes_nothing(tmp_path):
    root = installation(tmp_path)
    def denied(root):
        raise PermissionError('fixture')
    with pytest.raises(PermissionError):
        cleanup.prune('0.25.7', root=root, apply=True, scan=denied)
    assert len(list((root / 'releases').iterdir())) == 5


def test_wrong_current_aborts_before_scan(tmp_path):
    root = installation(tmp_path)
    with pytest.raises(RuntimeError, match='Current release'):
        cleanup.prune('0.25.6', root=root, apply=True, scan=lambda root: set())


def test_dry_run_and_external_symlink_never_delete(tmp_path):
    root = installation(tmp_path)
    outside = tmp_path / 'business-data'
    outside.mkdir()
    (outside / 'keep').write_text('fixture')
    (root / 'releases/0.1.0').symlink_to(outside)
    report = cleanup.prune('0.25.7', root=root, scan=lambda root: set())
    assert '0.1.0' not in report['selected']
    assert len(list((root / 'releases').iterdir())) == 6
    cleanup.prune('0.25.7', root=root, apply=True, scan=lambda root: set())
    assert (outside / 'keep').read_text() == 'fixture'


def test_process_and_inactive_service_references(tmp_path):
    root = tmp_path / 'opt'
    proc = tmp_path / 'proc/123'
    proc.mkdir(parents=True)
    (proc / 'fd').mkdir()
    (proc / 'cmdline').write_bytes((str(root / 'releases/0.25.5/bin/python') + '\0-I').encode())
    (proc / 'environ').write_bytes(b'')
    (proc / 'maps').write_text(str(root / 'releases/0.25.6/lib/native.so'))
    config = tmp_path / 'etc/systemd/system'
    config.mkdir(parents=True)
    (tmp_path / 'etc/cron.d').mkdir()
    (config / 'idle.service').write_text('ExecStart=' + str(root / 'releases/0.18.1/bin/python'))
    (config / 'retired.service').symlink_to('/missing/vendor.service')
    assert cleanup.consumers(root, tmp_path / 'proc', tmp_path / 'etc') == {'0.18.1', '0.25.5', '0.25.6'}
