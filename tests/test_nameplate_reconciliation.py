import importlib.util
import json
from pathlib import Path
import pytest
from PIL import Image
from taiko_bot.offline.nameplate_import import MODULE_MARKER

spec = importlib.util.spec_from_file_location('reconcile_nameplates', Path(__file__).resolve().parents[1] / 'scripts/readiness/reconcile-nameplates.py')
reconcile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconcile)


def service(rows=None):
    base = 'https://taiko-file.gzheyoukeji.com/title/'
    if rows is None:
        rows = [{'id': 947, 'rarity': 14, 'icon': base+'sister.png', 'dan_icon': base+'sister-dan.png'}]
    return MODULE_MARKER + ' var a=' + json.dumps(rows) + ';},"./next"'


def assets(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for suffix in ('14', '947', 'dani_14', 'dani_947'):
        with Image.new('RGBA', (556, 150), 'red') as image:
            image.save(source / f'name_plate_{suffix}.png')
    (source / 'name_plate_2_bg.png').write_bytes(b'derived fixture')
    return source


def test_reconcile_all_and_remove_only_verified_aliases(tmp_path):
    source = assets(tmp_path)
    result = reconcile.reconcile(service(), source, tmp_path/'stage', apply=True)
    assert len(result['files']) == 2
    assert set(result['removed']) == {'name_plate_947.png', 'name_plate_dani_947.png'}
    assert (source/'name_plate_14.png').is_file()
    assert (source/'name_plate_2_bg.png').read_bytes() == b'derived fixture'


def test_dry_run_reuses_aliases_and_preserves_source(tmp_path):
    source = assets(tmp_path)
    (source/'name_plate_14.png').unlink()
    result = reconcile.reconcile(service(), source, tmp_path/'stage')
    assert result['files']['name_plate_14.png']['reusedFrom'] == 'name_plate_947.png'
    assert not result['removed']
    assert (source/'name_plate_947.png').exists()
    assert not (source/'name_plate_14.png').exists()


def test_apply_recovers_missing_canonical_without_download(tmp_path):
    source = assets(tmp_path)
    (source/'name_plate_14.png').unlink()
    reconcile.reconcile(service(), source, tmp_path/'stage', apply=True)
    assert (source/'name_plate_14.png').exists()
    assert not (source/'name_plate_947.png').exists()


@pytest.mark.parametrize('damage', ['different', 'corrupt', 'missing', 'symlink'])
def test_any_catalog_failure_preserves_all_source_files(tmp_path, damage):
    source = assets(tmp_path)
    path = source/'name_plate_dani_14.png'
    if damage == 'different':
        with Image.new('RGBA', (556, 150), 'blue') as image:
            image.save(path)
    elif damage == 'corrupt':
        path.write_bytes(b'bad png')
    else:
        path.unlink()
        if damage == 'missing':
            (source/'name_plate_dani_947.png').unlink()
        else:
            path.symlink_to(source/'name_plate_dani_947.png')
    before = {p.name for p in source.iterdir()}
    with pytest.raises(ValueError):
        reconcile.reconcile(service(), source, tmp_path/'stage', apply=True)
    assert {p.name for p in source.iterdir()} == before


def test_reconciliation_can_run_again_without_obsolete_aliases(tmp_path):
    source = assets(tmp_path)
    reconcile.reconcile(service(), source, tmp_path/'first', apply=True)
    result = reconcile.reconcile(service(), source, tmp_path/'second', apply=True)
    assert not result['obsolete']
    assert len(result['files']) == 2


def test_obsolete_id_that_is_also_canonical_is_never_deleted(tmp_path):
    source = assets(tmp_path)
    for prefix in ('name_plate_', 'name_plate_dani_'):
        (source/f'{prefix}15.png').write_bytes((source/f'{prefix}14.png').read_bytes())
    base = 'https://taiko-file.gzheyoukeji.com/title/'
    text = service([{'id': 947, 'rarity': 14, 'icon': base+'a.png', 'dan_icon': base+'b.png'},
                    {'id': 14, 'rarity': 15, 'icon': base+'c.png', 'dan_icon': base+'d.png'}])
    result = reconcile.reconcile(text, source, tmp_path/'stage', apply=True)
    assert len(result['files']) == 4
    assert 'name_plate_14.png' not in result['removed']
    assert (source/'name_plate_14.png').exists()
