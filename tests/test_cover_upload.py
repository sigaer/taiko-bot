"""Offline cover uploads and real center/client handler bodies; no remote writes."""
import ast
import asyncio
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'taiko_bot/runtime/community/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = load_helper('cover_upload')
concurrency = load_helper('concurrency')


class CoverUpload(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['QA_RUN_TMPDIR'])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / '1529.png'
        with Image.new('RGB', (400, 400), 'blue') as image:
            image.save(self.original)

    def test_upload_original_and_derivatives(self):
        digest = hashlib.sha256(self.original.read_bytes()).hexdigest()
        with patch.object(module.subprocess, 'run') as run:
            self.assertTrue(module.upload_cover(self.original)[0])
        self.assertEqual(run.call_count, 3)
        for call, key in zip(run.call_args_list, ('1529.png', 'thumb/200/1529.webp', 'thumb/400/1529.webp')):
            self.assertEqual(call.args[0][4], 'oss://sigaer/cover/' + key)
        self.assertEqual(hashlib.sha256(self.original.read_bytes()).hexdigest(), digest)
        for size in (200, 400):
            with Image.open(self.root / 'thumb' / str(size) / '1529.webp') as image:
                self.assertEqual(image.size, (size, size))
                self.assertEqual(image.format, 'WEBP')

    def test_partial_failure_without_retry_message(self):
        def upload(args, **kwargs):
            if '/200/' in args[4]:
                raise RuntimeError('controlled failure')
        with patch.object(module.subprocess, 'run', side_effect=upload) as run:
            ok, detail = module.upload_cover(self.original)
        self.assertFalse(ok)
        self.assertIn('原图已上传到 OSS', detail)
        self.assertIn('缩略图上传失败', detail)
        self.assertNotIn('重试', detail)
        self.assertEqual(run.call_count, 3)

    def test_auth_failure_sanitized_and_stops_further_uploads(self):
        for code in ('InvalidAccessKeyId', 'SignatureDoesNotMatch', 'AccessDenied'):
            with self.subTest(code=code):
                error = subprocess.CalledProcessError(1, ['ossutil'], output=(code + ' secret-sentinel').encode())
                with patch.object(module.subprocess, 'run', side_effect=error) as run:
                    ok, detail = module.upload_cover(self.original)
                self.assertFalse(ok)
                self.assertIn('请联系管理员', detail)
                self.assertNotIn('secret-sentinel', detail)
                self.assertNotIn('重试', detail)
                self.assertEqual(run.call_count, 1)
                self.assertTrue(self.original.exists())

    def test_thumbnail_failure_without_upload(self):
        with patch.object(module.Image, 'open', side_effect=OSError), patch.object(module.subprocess, 'run') as run:
            ok, detail = module.upload_cover(self.original)
        self.assertFalse(ok)
        self.assertIn('缩略图生成失败', detail)
        self.assertNotIn('重试', detail)
        run.assert_not_called()


class Finished(Exception):
    pass


class Capture:
    async def finish(self, message):
        raise Finished(message)


class CoverCommands(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['QA_RUN_TMPDIR'])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = io.BytesIO()
        with Image.new('RGB', (33, 47), 'blue') as image:
            image.save(raw, 'PNG')
        self.png = raw.getvalue()

    def handler(self, role, uploaded=True):
        root = self.root / role
        root.mkdir(exist_ok=True)
        catalog = root / 'song_data.json'
        catalog.write_text(json.dumps([{'id': 1}]))
        download = Mock()
        png = self.png

        class HTTP:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def get(self, url):
                download(url)
                return types.SimpleNamespace(content=png, raise_for_status=lambda: None)

        async def group_name(*args): return 'fixture-group'

        upload = Mock(return_value=(uploaded, 'OSS 上传凭据无效，请联系管理员'))
        audit = Mock()
        ns = dict(asyncio=asyncio, serialized=concurrency.serialized,
                  COVER_DIR=root, SONG_DATA_PATH=catalog, json=json, Image=Image,
                  BytesIO=io.BytesIO, RegexGroup=lambda: None, cover_cmd=Capture(),
                  httpx=types.SimpleNamespace(AsyncClient=HTTP),
                  _upload_cover_to_oss=upload, write_admin_action_log=audit,
                  _event_group_scope_id=lambda event: 'fixture-group',
                  _extract_uploader_group_name=group_name,
                  _extract_cover_command_match=lambda event: re.match(r'cover\s*(\d+)', event.text))
        source = ast.parse((ROOT / f'taiko_bot/runtime/community/{role}/cover.py').read_text())
        handler = next(node for node in source.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'handle_cover')
        handler.decorator_list = []
        tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), handler], type_ignores=[])
        exec(compile(ast.fix_missing_locations(tree), f'{role}/cover.py', 'exec'), ns)

        async def invoke(song_id='1'):
            event = types.SimpleNamespace(text='cover' + song_id,
                get_message=lambda: [types.SimpleNamespace(type='image', data={'url': 'https://fixture.invalid/image'})],
                get_user_id=lambda: 'fixture-user')
            kwargs = {'reg_group': (song_id,)} if role == 'client' else {}
            try:
                await ns['handle_cover'](object(), event, **kwargs)
            except Finished as error:
                return str(error)
            self.fail('handler did not finish')
        return invoke, upload, download, audit, root

    async def test_both_roles_save_upload_and_reject_duplicates(self):
        for role in ('center', 'client'):
            with self.subTest(role=role):
                invoke, upload, download, audit, root = self.handler(role)
                self.assertIn('上传成功', await invoke('0001'))
                self.assertTrue((root / '1.png').exists())
                digest = hashlib.sha256((root / '1.png').read_bytes()).hexdigest()
                self.assertIn('已存在', await invoke())
                self.assertIn('已存在', await invoke('0001'))
                upload.assert_called_once_with(root / '1.png')
                self.assertEqual(download.call_count, 1)
                self.assertEqual(hashlib.sha256((root / '1.png').read_bytes()).hexdigest(), digest)

    async def test_failure_preserves_local_cover_and_rejects_duplicates(self):
        for role in ('center', 'client'):
            with self.subTest(role=role):
                invoke, upload, download, audit, root = self.handler(role, uploaded=False)
                result = await invoke()
                self.assertIn('本地封面已保存', result)
                self.assertIn('OSS 上传凭据无效', result)
                self.assertNotIn('重试', result)
                self.assertIn('已存在', await invoke())
                self.assertEqual(upload.call_count, 1)
                if role == 'center':
                    self.assertFalse(audit.call_args.kwargs['extra']['oss_synced'])

    async def test_concurrent_commands_upload_once(self):
        for role in ('center', 'client'):
            with self.subTest(role=role):
                invoke, upload, download, audit, root = self.handler(role)
                results = await asyncio.gather(invoke(), invoke('0001'))
                self.assertEqual(sum('上传成功' in result for result in results), 1)
                self.assertEqual(sum('已存在' in result for result in results), 1)
                self.assertEqual(upload.call_count, 1)
                self.assertEqual(download.call_count, 1)
        self.assertFalse(concurrency._pending)


if __name__ == '__main__':
    unittest.main()
