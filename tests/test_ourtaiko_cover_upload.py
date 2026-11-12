"""Synthetic contract checks for the standalone upload tool (no network)."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from ourtaiko_covers.client import APIError, BASE, Client, Forms
from ourtaiko_covers.matching import build_plan

spec = importlib.util.spec_from_file_location('uploader', SCRIPTS / 'upload_ourtaiko_covers.py')
uploader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uploader)


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=os.environ.get('QA_RUN_TMPDIR'))
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.cid = 'a' * 32
        Image.new('RGB', (8, 8), 'red').save(self.root / '123.png')

    def plan(self, chart, songs):
        (self.root / 'charts.json').write_text(json.dumps({'charts': [chart]}))
        (self.root / 'songs.json').write_text(json.dumps(songs))
        return build_plan(self.root / 'charts.json', self.root / 'songs.json', self.root)['rows'][0]

    def test_database_export_uses_explicit_id_mapping(self):
        row = self.plan({'id': self.cid, 'nijiiro_id': 123},
                        [{'id': 123, 'ourtaiko_ids': [self.cid]}])
        self.assertEqual(row['status'], 'ready')
        self.assertEqual(row['matchedBy'], ['nijiiro', 'source'])
        self.assertEqual(row['localId'], '123')

    def test_non_nijiiro_mapping_uses_local_id_not_number_id(self):
        row = self.plan({'id': self.cid, 'number_id': 999},
                        [{'id': 123, 'ourtaiko_ids': [self.cid]}])
        self.assertEqual(row['status'], 'ready')
        self.assertTrue(row['path'].endswith('/123.png'))

    def test_conflicting_identifiers_never_upload(self):
        row = self.plan({'id': self.cid, 'nijiiro_id': 456},
                        [{'id': 123, 'ourtaiko_ids': [self.cid]}, {'id': 456}])
        self.assertEqual(row['status'], 'ambiguous')
        row = self.plan({'id': self.cid, 'nijiiro_id': 456},
                        [{'id': 123, 'ourtaiko_ids': [self.cid]}])
        self.assertEqual(row['status'], 'identifier_conflict')

    def test_matching_title_alone_is_insufficient(self):
        row = self.plan({'id': self.cid, 'title': 'Song'}, [{'id': 123, 'song_name': 'Song'}])
        self.assertEqual(row['status'], 'unmatched')

    def test_invalid_cover_and_missing_cover(self):
        (self.root / '123.png').write_bytes(b'not an image')
        row = self.plan({'id': self.cid, 'nijiiro_id': 123}, [{'id': 123}])
        self.assertEqual(row['status'], 'invalid_cover')
        (self.root / '123.png').unlink()
        row = self.plan({'id': self.cid, 'nijiiro_id': 123}, [{'id': 123}])
        self.assertEqual(row['status'], 'missing_cover')

    def test_resume_ignores_failed_or_incomplete_records(self):
        path = self.root / 'uploads.jsonl'
        row = dict(base=BASE, chartId=self.cid, sourceSha256='hash', status='uploaded', coverHash='stored')
        path.write_text(json.dumps(row) + '\n' + json.dumps({**row, 'status': 'failed'}) + '\n{')
        self.assertEqual(uploader.completed(path)[(self.cid, 'hash')]['coverHash'], 'stored')

    def test_jpeg_bytes_in_png_path_upload_with_jpg_filename(self):
        path = self.root / '123.png'
        Image.new('RGB', (8, 8), 'blue').save(path, format='JPEG')
        original = path.read_bytes()
        client = Client()
        client.request = Mock()
        client.json = Mock(return_value={'coverHash': 'b' * 64})
        client.chart = Mock(return_value={'coverHash': 'b' * 64})
        client.put_cover(self.cid, path)
        self.assertEqual(client.request.call_args.kwargs['files']['cover'][0], '123.jpg')
        self.assertEqual(path.read_bytes(), original)


class ClientTests(unittest.TestCase):
    def test_form_parser_selects_login_form_not_language_form(self):
        forms = Forms('<form><input name="next" value="wrong"></form><form>'
                      '<input name="password"><input name="next" value="/o/?a=1&amp;b=2"></form>').forms
        self.assertEqual(next(f for f in forms if 'password' in f)['next'], '/o/?a=1&b=2')

    def test_rate_limit_is_retried_without_tight_loop(self):
        client = Client()
        client.session = Mock()
        client.session.request.side_effect = [Mock(status_code=429, headers={}), Mock(status_code=200)]
        with patch('ourtaiko_covers.client.time.sleep') as sleep:
            response = client.request('PUT', BASE + '/test')
        self.assertEqual(response.status_code, 200)
        self.assertIn(65, [call.args[0] for call in sleep.call_args_list])

    def test_auth_error_is_never_retried(self):
        client = Client()
        client.session = Mock()
        response = Mock(status_code=403)
        response.json.return_value = {'code': 'FORBIDDEN', 'message': 'private detail'}
        client.session.request.return_value = response
        with self.assertRaisesRegex(APIError, '^HTTP 403: FORBIDDEN$'):
            client.json(client.request('GET', BASE + '/test'))
        self.assertEqual(client.session.request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
