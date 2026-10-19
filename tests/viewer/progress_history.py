"""Installed Viewer -> canonical synthetic history -> real Dani renderer.

Run with -I under the bounded QA runner. No production data, SQL or sockets.
"""
import argparse, contextlib, copy, hashlib, io, json, os, resource, runpy, shutil, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

p = argparse.ArgumentParser()
p.add_argument('--expect-baseline-bug', action='store_true')
p.add_argument('--prepare-fixture', type=Path)
a = p.parse_args()
resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024**2, 1024 * 1024**2))
resource.setrlimit(resource.RLIMIT_CPU, (100, 100))
scratch = None if a.prepare_fixture else tempfile.TemporaryDirectory(prefix='progress-history-', dir='/var/tmp')
root = a.prepare_fixture.resolve() if a.prepare_fixture else Path(scratch.name)
assert root.is_relative_to('/var/tmp') and root != Path('/var/tmp')
root.mkdir(mode=0o700, parents=True, exist_ok=True)
os.environ.update({key: str(root) for key in ('TAIKO_OFFLINE_ROOT', 'TAIKO_CENTER_ROOT', 'TAIKO_RUNTIME_ROOT')})
os.environ.update(TAIKO_USERDATA_DIR=str(root/'userdata'), TAIKO_RUNTIME_ENV_FILE=str(root/'absent.env'),
                  TAIKO_COMPUTE_ONLY='1', MPLCONFIGDIR=str(root/'mpl'), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
os.chdir(root)

def guard(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'sqlite3.connect'):
        raise AssertionError('External IO forbidden')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0])
        if path.startswith(('/home/sigaer/taiko/', '/home/sigaer/git/', '/etc/taiko', '/root/.ossutil')):
            raise AssertionError('Production data forbidden')
sys.addaudithook(guard)

fixture = runpy.run_path(str(Path(__file__).resolve().parents[2]/'packages/taiko-application/tests/fixture.py'))['FIXTURE']
complete_conditions = next(grade['conditions'] for grade in fixture['grade_payload']['grades'] if grade['songs'])
for grade in fixture['grade_payload']['grades']:
    if not grade['songs']:
        grade['conditions'] = copy.deepcopy(complete_conditions)
(root/'songs').mkdir()
values = {
    'song_data.json': fixture['song_catalog'], 'song_alias.json': [], 'song_score.json': [],
    'song_difficulty.json': {},
    'song_id2tjapath.json': {}, 'rating_structured_with_ids.json': fixture['rating_config'],
    'taiko_goku_onis.json': fixture['roll_catalog'], 'taiko_goku_all_levels_stream.json': [],
    'grade_dojo_nijiiro_history_simple.json': {'versions': {str(y): fixture['grade_payload'] for y in range(2010, 2027)}}
}
for version in ('2025', '2026'):
    values[f'grade_dojo_nijiiro_{version}_simple.json'] = dict(fixture['grade_payload'], year=version)
for name, value in values.items(): (root/'songs'/name).write_text(json.dumps(value))
from PIL import Image
for name, size in [('templates/dani_up.png', (1280, 900)), ('templates/dani_down.png', (1280, 1800))]:
    path = root/'assets'/name; path.parent.mkdir(parents=True, exist_ok=True)
    with Image.new('RGBA', size, (245, 240, 230, 255)) as image: image.save(path)
for folder in ('diff', 'dani'):
    for name in [str(i) for i in range(1, 30)] + ['bar', 'bar_4', 'bar_5']:
        path = root/'assets/icons'/folder/(name+'.png'); path.parent.mkdir(parents=True, exist_ok=True)
        with Image.new('RGBA', (80, 30), (100, 150, 190, 255)) as image: image.save(path)
(root/'assets/fonts').mkdir()
font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
for name in ('DDFont.ttf', 'FZPW_GBK.ttf'): shutil.copyfile(font, root/'assets/fonts'/name)

from taiko_store import PublicationStore, PublicationError
from taiko_bot.offline import viewer
from taiko_bot.runtime.player.center.progress_support import dani_progress as dani

def payload(version='2026', scores=True, dojo=False):
    value = copy.deepcopy(fixture['userdata'])
    if not scores: value['songs'] = []
    value['dojo'] = {'version': version, 'scores': []}
    if dojo:
        value['dojo']['scores'] = [dict(dan_id=11, marker=version, level_icon=2)]
    return value

def source(identity, current, history):
    store = PublicationStore(root/'userdata', identity)
    files = {'current': json.dumps(current).encode()}
    files.update({'history/'+name: json.dumps(value).encode() for name, value in history.items()})
    with store.exclusive(): store.commit(files)
    return store

def digest(png):
    assert isinstance(png, bytes) and png.startswith(b'\x89PNG\r\n\x1a\n')
    with Image.open(io.BytesIO(png)) as image: image.verify()
    return hashlib.sha256(png).hexdigest()

if a.prepare_fixture:
    source('114514', payload(), {'data_20261018_100000_000000.json': payload('2025', dojo=True)})
    source('114516', payload(scores=False), {})
    print(json.dumps({'synthetic_fixture_ready': True}))
    sys.exit(0)

class ProgressHistory(unittest.TestCase):
    def test_history_fallback_preserves_filename_order_and_pixels(self):
        current = payload()
        history = {'data_2026-10-18_10_00_00.json': payload('2025', dojo=True),
                   'data_20261001_100000_000000.json': payload('2025', dojo=True),
                   'data_20261019_100000_000000.json': payload('2026', dojo=True)}
        history['data_20261001_100000_000000.json']['dojo']['scores'][0]['marker'] = 'filename-latest-2025'
        store = source('114514', current, history)
        if a.expect_baseline_bug:
            with self.assertRaisesRegex(KeyError, 'fileName'):
                viewer.render_dani_progress_image_bytes(114514, '六段', version='2025', explicit_version=True)
            with store.exclusive(): pass
            return
        actual = viewer.render_dani_progress_image_bytes(114514, '六段', version='2025', explicit_version=True)
        expected = dani.render_dani_progress_image_bytes(114514, '六段', version='2025', explicit_version=True,
            userdata=current, history_snapshots=[dict(fileName=name, payload=value) for name, value in history.items()])
        self.assertEqual(digest(actual), digest(expected))
        selected = dani._load_dojo_progress_payload(current, [dict(fileName=k, payload=v) for k,v in history.items()], 11, '2025')
        self.assertEqual(selected['scores'][0]['marker'], 'filename-latest-2025')
        with store.exclusive(): pass

    @unittest.skipIf(a.expect_baseline_bug, 'baseline reproduction only')
    def test_current_dojo_and_empty_data_remain_real_png(self):
        for identity, current in [('114515', payload('2026', dojo=True)), ('114516', payload(scores=False))]:
            store = source(identity, current, {})
            actual = viewer.render_dani_progress_image_bytes(int(identity), '六段', version='2026', explicit_version=True)
            expected = dani.render_dani_progress_image_bytes(int(identity), '六段', version='2026', explicit_version=True, userdata=current, history_snapshots=[])
            self.assertEqual(digest(actual), digest(expected))
            with store.exclusive(): pass

    @unittest.skipIf(a.expect_baseline_bug, 'baseline reproduction only')
    def test_missing_chart_keeps_owner_notice_and_png(self):
        current = payload(scores=False)
        source('114517', current, {})
        # A valid grade with no available task charts stays the renderer's notice.
        actual = viewer.render_dani_progress_image_bytes(114517, '五級', version='2026')
        expected = dani.render_dani_progress_image_bytes(114517, '五級', version='2026', userdata=current, history_snapshots=[])
        self.assertEqual(digest(actual), digest(expected))

    @unittest.skipIf(a.expect_baseline_bug, 'baseline reproduction only')
    def test_render_failure_releases_canonical_lease(self):
        store = source('114518', payload(), {'data_20261018_100000_000000.json': payload('2025', dojo=True)})
        with patch.object(dani.DaniProgressRenderer, 'render', side_effect=OSError('synthetic render failure')):
            with self.assertRaisesRegex(OSError, 'synthetic render failure'):
                viewer.render_dani_progress_image_bytes(114518, '六段', version='2025')
        with store.exclusive(): pass

    @unittest.skipIf(a.expect_baseline_bug, 'baseline reproduction only')
    def test_malformed_historical_json_keeps_exclusion(self):
        store = source('114519', payload(), {})
        with store.exclusive(): store.commit({'history/data_20261018_100000_000000.json': b'not-json'})
        digest(viewer.render_dani_progress_image_bytes(114519, '六段', version='2025'))
        with store.exclusive(): pass

    @unittest.skipIf(a.expect_baseline_bug, 'baseline reproduction only')
    def test_corrupt_canonical_history_fails_closed_and_releases_lease(self):
        name = 'data_20261018_100000_000000.json'
        store = source('114520', payload(), {name: payload('2025', dojo=True)})
        with store.shared(): ref = store.reader().manifest['files']['history/'+name]
        (store.objects/ref['sha256']).write_bytes(b'corrupt')
        with self.assertRaises(PublicationError): viewer.render_dani_progress_image_bytes(114520, '六段', version='2025')
        with store.exclusive(): pass

    @unittest.skipIf(a.expect_baseline_bug, 'baseline reproduction only')
    def test_missing_source_is_an_error(self):
        with self.assertRaises(FileNotFoundError): viewer.render_dani_progress_image_bytes(114521, '六段', version='2025')

try:
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProgressHistory))
    print(json.dumps({'status': 'PASS' if result.wasSuccessful() else 'FAIL', 'tests': result.testsRun,
                      'baseline_reproduced': a.expect_baseline_bug and result.wasSuccessful(),
                      'production_reads': False, 'database_or_network': False,
                      'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
    sys.exit(0 if result.wasSuccessful() else 1)
finally:
    if scratch is not None: scratch.cleanup()
