"""Real installed QQ builders; synthetic images, no network or player data."""
import asyncio
import importlib
from io import BytesIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image
from nonebot.adapters.qq import Bot
from taiko_bot.runtime import qq_images
from taiko_bot.runtime.player.authority import AuthorizedDelivery, TinfoDenied

BUILDERS = (
    'taiko_bot.runtime.player.center.messages',
    'taiko_bot.runtime.player.client.messages',
    'taiko_bot.runtime.public.center_messages',
    'taiko_bot.runtime.public.client_messages',
    'taiko_bot.runtime.center_platform_adapter',
    'taiko_runtime.platform_adapter',
)
SENDERS = tuple(name for name in BUILDERS if '.public.' not in name)


class QQEvent:
    __module__ = 'nonebot.adapters.qq.event'
    id = 'fixture-event'
    group_openid = 'fixture-group'


class Matcher:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(message)
        return 'sent'

    async def finish(self, *args, **kwargs):
        self.finished = (args, kwargs)
        return 'finished'


class QQImageDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stream = BytesIO()
        Image.new('RGB', (12, 24), 'blue').save(stream, 'JPEG')
        cls.jpeg = stream.getvalue()

    def test_all_six_builders_use_markdown_without_reference_or_upload(self):
        for name in BUILDERS:
            with self.subTest(module=name):
                module = importlib.import_module(name)
                with patch.object(module, 'cache_markdown_image_url', return_value='https://fixture.invalid/image.jpg') as cache:
                    message = module._build_qq_reply_message(QQEvent(), text='feedback', image_bytes=self.jpeg)
                self.assertEqual([s.type for s in message], ['markdown'])
                self.assertIn('feedback', message[0].data['markdown'].content)
                self.assertIn('![img#12px #24px]', message[0].data['markdown'].content)
                kwargs = Bot._extract_send_message(message, escape_text=False)
                payload = Bot._parse_send_message({**kwargs, 'msg_type':2, 'msg_id':'fixture-event'})['json']
                self.assertNotIn('media', payload)
                self.assertNotIn('content', payload)
                self.assertNotIn('message_reference', payload)
                cache.assert_called_once()

    def test_default_and_explicit_old_preference_share_same_policy(self):
        for name in SENDERS:
            module = importlib.import_module(name)
            for preference in (False, True):
                with self.subTest(module=name, preference=preference):
                    matcher = Matcher()
                    with patch.object(module, 'cache_markdown_image_url', return_value='https://fixture.invalid/image.jpg'):
                        result = asyncio.run(module.send_image_reply(matcher, QQEvent(), self.jpeg,
                            prefix_text='feedback', quick_actions=True, prefer_markdown_image=preference))
                    self.assertEqual(result, 'finished')
                    self.assertEqual(len(matcher.messages), 1)
                    self.assertEqual([s.type for s in matcher.messages[0]], ['markdown', 'keyboard'])
                    self.assertIn('feedback', matcher.messages[0][0].data['markdown'].content)

    def test_bot_sender_also_sends_one_markdown_message(self):
        for name in SENDERS:
            module = importlib.import_module(name)
            bot = SimpleNamespace(send=AsyncMock(return_value='sent'))
            with patch.object(module, 'cache_markdown_image_url', return_value='https://fixture.invalid/image.jpg'):
                self.assertEqual(asyncio.run(module.send_image_reply(bot, QQEvent(), self.jpeg)), 'sent')
            self.assertEqual(bot.send.await_count, 1)
            self.assertEqual([s.type for s in bot.send.call_args.args[1]], ['markdown'])

    def test_known_passive_limit_preserves_existing_proactive_markdown_fallback(self):
        for name in (SENDERS[0], 'taiko_bot.runtime.center_platform_adapter'):
            module = importlib.import_module(name)
            matcher = Matcher()
            matcher.send = AsyncMock(side_effect=RuntimeError('40034128'))
            with patch.object(module, 'cache_markdown_image_url', return_value='https://fixture.invalid/image.jpg'), \
                 patch.object(module, '_send_qq_proactive', new=AsyncMock(return_value=True)) as proactive:
                asyncio.run(module.send_image_reply(matcher, QQEvent(), self.jpeg))
            self.assertEqual(matcher.send.await_count, 1)
            proactive.assert_awaited_once()
            self.assertEqual([s.type for s in proactive.call_args.args[2]], ['markdown'])

    def test_timeout_does_not_retry_or_fall_back_to_upload(self):
        for name in SENDERS:
            module = importlib.import_module(name)
            matcher = Matcher()
            matcher.send = AsyncMock(side_effect=TimeoutError('fixture'))
            with patch.object(module, 'cache_markdown_image_url', return_value='https://fixture.invalid/image.jpg'):
                with self.assertRaises(TimeoutError):
                    asyncio.run(module.send_image_reply(matcher, QQEvent(), self.jpeg))
            self.assertEqual(matcher.send.await_count, 1)

    def test_local_cache_failure_keeps_existing_media_fallback(self):
        for name in SENDERS:
            module = importlib.import_module(name)
            matcher = Matcher()
            image = BytesIO(self.jpeg)
            image.seek(7)
            with patch.object(module, 'cache_markdown_image_url', side_effect=OSError('fixture')):
                asyncio.run(module.send_image_reply(matcher, QQEvent(), image, prefix_text='feedback'))
            self.assertEqual(len(matcher.messages), 1)
            self.assertEqual(len(matcher.messages[0]['file_image']), 1)
            self.assertEqual(image.tell(), 0)

    def test_revocation_blocks_publication_and_send(self):
        for name in SENDERS:
            module = importlib.import_module(name)
            provider = SimpleNamespace(verify=lambda prepared: (_ for _ in ()).throw(TinfoDenied()))
            matcher = Matcher()
            facade = AuthorizedDelivery(matcher, provider, object())
            with patch.object(module, 'cache_markdown_image_url') as cache:
                with self.assertRaises(TinfoDenied):
                    asyncio.run(module.send_image_reply(facade, QQEvent(), self.jpeg))
            cache.assert_not_called()
            self.assertEqual(matcher.messages, [])

    def test_private_delivery_is_rechecked_before_cache_and_before_send(self):
        module = importlib.import_module(SENDERS[0])
        checks = []
        provider = SimpleNamespace(verify=lambda prepared: checks.append('verify'))
        matcher = Matcher()
        def cache(*args, **kwargs):
            self.assertEqual(checks, ['verify'])
            return 'https://fixture.invalid/image.jpg'
        with patch.object(module, 'cache_markdown_image_url', side_effect=cache):
            asyncio.run(module.send_image_reply(AuthorizedDelivery(matcher, provider, object()), QQEvent(), self.jpeg))
        self.assertEqual(checks, ['verify', 'verify'])

    def test_onebot_never_publishes_an_image(self):
        for name in SENDERS:
            module = importlib.import_module(name)
            matcher = Matcher()
            with patch.object(module, 'cache_markdown_image_url', side_effect=AssertionError('must not publish')):
                asyncio.run(module.send_image_reply(matcher, object(), self.jpeg, prefix_text='feedback'))
            message = matcher.finished[0][0]
            self.assertEqual([s.type for s in message], ['text', 'image'])
            self.assertEqual(matcher.finished[1], {'reply_message': True})

    def test_atomic_publication_and_cleanup_under_private_umask(self):
        for name in ('taiko_bot.runtime.center_markdown_media', 'taiko_runtime.qq_markdown_media'):
            module = importlib.import_module(name)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)/'cache'
                old_umask = os.umask(0o077)
                try:
                    with patch.object(module, 'QQ_MARKDOWN_IMAGE_CACHE_DIR', root), patch.object(module, 'QQ_MARKDOWN_IMAGE_BASE_URL', 'https://fixture.invalid/cache'):
                        url = module.cache_markdown_image_url(BytesIO(self.jpeg))
                        path = root/url.rsplit('/', 1)[1]
                        self.assertEqual(path.read_bytes(), self.jpeg)
                        self.assertEqual(path.stat().st_mode&0o777, 0o644)
                        self.assertEqual(root.stat().st_mode&0o777, 0o755)
                        self.assertEqual(module.cleanup_expired_markdown_images(now=path.stat().st_mtime+module.QQ_MARKDOWN_IMAGE_TTL_SECONDS+1), 1)
                        self.assertEqual(list(root.iterdir()), [])
                finally:
                    os.umask(old_umask)

    def test_failed_publication_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(qq_images.os, 'replace', side_effect=OSError('fixture')):
                with self.assertRaises(OSError):
                    qq_images.write_public_image(root, 'fixture.jpg', self.jpeg)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
