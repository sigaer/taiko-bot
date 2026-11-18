"""Adapter regressions against installed Core 0.1.1 (no algorithm stubs).

Run: python -m unittest discover -s tests/recommendation -p test_empty_shelf.py -v
Only the thin recommendation adapter and JSON loader functions are compiled from
source, as in wheel_cache_smoke.py, to avoid importing Bot/presentation drivers.
This is not a matcher, authorization or Viewer end-to-end test.
"""
import ast
from functools import partial
from importlib.metadata import version
import json
from pathlib import Path
import tempfile
import unittest

from sakura_taiko_core.chart import availability
from sakura_taiko_core.recommendation import candidates

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = (
    ('taiko_bot/runtime/player/center/recommendation_support/score_calculator.py',
     'taiko_bot/runtime/player/center/recommendation_support/chart_availability.py'),
    ('taiko_bot/offline/score_calculator.py', 'taiko_bot/offline/chart_availability.py'),
)
DIMENSIONS = ('rating', 'daigouryoku', 'stamina', 'speed', 'accuracy_power', 'rhythm', 'complex')


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == set(names)
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *functions], type_ignores=[])),
                 str(path), 'exec'), namespace)
    return namespace


def fixtures():
    # 21 played charts exercise best20 exclusion and a played candidate; the
    # other charts exercise unplayed sorting, limit and duplicate identity.
    songs = {}
    records = []
    rows = []
    for song_id in range(10001, 10026):
        songs[str(song_id)] = dict(id=song_id, level=4, title=f'Song {song_id}',
            score=10, combo=100, **{'复合处理': 50, '平均密度': 50,
                                   '瞬间密度': 50, '叩き分け': 50, 'BPM变化': 0})
        rows.append(dict(id=song_id, level_4=9, shelf_status=0))
        if song_id <= 10021:
            records.append(dict(song_no=song_id, level=4, good_cnt=90, ok_cnt=10))
    cfg = dict(songs=songs, const_table={'const_to_score': {'10': 10}})
    return rows, cfg, records


class EmptyShelfRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Deliberately fail rather than skip or silently validate another Core.
        if version('sakura-taiko-core') != '0.1.1':
            raise AssertionError('Run in the pinned center Core 0.1.1 environment')

    def test_catalog_scenarios(self):
        for entry, loader in ENTRIES:
            for scenario in ('normal', 'partial', 'all_down', 'raw_only', 'no_charts', 'empty'):
                with self.subTest(entry=entry, scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    rows, cfg, records = fixtures()
                    raw = None
                    if scenario in ('all_down', 'raw_only'):
                        for index, row in enumerate(rows):
                            row['shelf_status'] = (1, '1', '已下架')[index % 3]
                    if scenario == 'partial':
                        rows[-1]['shelf_status'] = '已下架'
                    if scenario == 'raw_only':
                        # Independent catalog snapshots: a structurally available
                        # raw song absent from the entirely off-shelf merged list.
                        raw = [dict(id=10025, level_4=9)]
                        rows = rows[:-1]
                    if scenario == 'no_charts':
                        for row in rows:
                            row['level_4'] = '-'
                    if scenario == 'empty':
                        rows = []
                    path = root / 'song_data.json'
                    path.write_text(json.dumps(rows), encoding='utf-8')
                    if raw is not None:
                        path.with_name('song_data_raw.json').write_text(json.dumps(raw), encoding='utf-8')
                    loaders = load_functions(ROOT / loader,
                        ('_load_song_data', 'load_on_shelf_song_ids', 'load_cn_available_chart_keys'),
                        dict(json=json, Path=Path, _ROOT=root, _runtime_root=lambda: root,
                             domain_availability=availability))
                    available = loaders['load_cn_available_chart_keys'](path)
                    shelf = loaders['load_on_shelf_song_ids'](path)
                    defaults = {10024: 10023, 10023: 10023}
                    adapter = load_functions(ROOT / entry, ('recommend_songs',), dict(
                        identity_inputs=lambda: (defaults, [(10023, 10024)]),
                        load_cn_available_chart_keys=partial(loaders['load_cn_available_chart_keys'], path),
                        load_on_shelf_song_ids=partial(loaders['load_on_shelf_song_ids'], path),
                        domain_candidates=candidates))['recommend_songs']
                    stats, songs, table = candidates.build_all_stats_from_records(records, cfg, default_ids=defaults)
                    for dimension in DIMENSIONS:
                        for limit in (1, 20):
                            with self.subTest(dimension=dimension, limit=limit):
                                old_result = candidates.recommend_songs(stats, songs, table, dimension, limit,
                                    default_ids=defaults, cn_available_chart_keys=available, on_shelf_song_ids=shelf)
                                result = adapter(stats, songs, table, dimension, limit)
                                if scenario in ('normal', 'partial'):
                                    self.assertTrue(old_result, 'fixture must exercise real candidates')
                                    self.assertEqual(result, old_result)  # full DTO + order, no formula oracle copy
                                    self.assertTrue(all(r['song_id'] in shelf for r in result))
                                    self.assertTrue(all((r['song_id'], r['level']) in available for r in result))
                                    ids = [defaults.get(r['song_id'], r['song_id']) for r in result]
                                    self.assertEqual(len(ids), len(set(ids)))
                                else:
                                    self.assertEqual(result, [])
                                if scenario == 'raw_only':
                                    self.assertTrue(available)
                                    self.assertFalse(shelf)
                                    self.assertTrue(old_result, 'must reproduce the pinned Core defect')


if __name__ == '__main__':
    unittest.main()
