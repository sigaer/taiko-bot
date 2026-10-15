import asyncio
import importlib.util
import io
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image

from taiko_bot.runtime.community.center import annual_report_command as m

class CommandTests(unittest.TestCase):
    def test_aliases_and_real_qq_message_shape(self):
        self.assertEqual(len(m.COMMANDS), 8)
        self.assertIn('虹2025年度总结', m.COMMANDS)
        b = io.BytesIO(); Image.new('RGB', (1080,1872)).save(b, 'PNG')
        with patch.object(m, 'cache_markdown_image_url', return_value='https://viewer.sakura-bot.cn/test.png'):
            message = m.build_report_message(b.getvalue())
        self.assertEqual([s.type for s in message], ['markdown','keyboard'])
        self.assertIn(m.REPORT_TEXT, str(message[0]))
        self.assertIn('1080px #1872px', str(message[0]))
        keyboard = message[1].data['keyboard']
        button = keyboard.content.rows[0].buttons[0]
        self.assertEqual(button.action.type, 0)
        self.assertEqual(button.action.data, m.REPORT_URL)

    def test_non_official_is_silent(self):
        class Matcher:
            async def send(self, value): raise AssertionError('OneBot must not send')
        with patch.object(m, 'is_qq_official_event', return_value=False):
            asyncio.run(m.handle_annual_report(Matcher(), object()))

    def test_timeout_is_not_retried(self):
        calls=[]
        class Client:
            def __init__(self, **kwargs): self.kwargs=kwargs
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def stream(self,*args,**kwargs):
                calls.append(args)
                raise m.httpx.ReadTimeout('bounded test')
        with patch.dict(m.os.environ, {'TAIKO_BOT_SERVICE_TOKEN':'test-only'}), patch.object(m.httpx,'AsyncClient',Client):
            with self.assertRaises(m.AnnualReportError): asyncio.run(m.fetch_annual_card('qq_official:test'))
        self.assertEqual(len(calls),1)


class LimitsTests(unittest.TestCase):
    def setUp(self):
        m._active.clear(); m._cooldown.clear()

    def tearDown(self):
        m._active.clear(); m._cooldown.clear()

    def test_status_invalid_png_size_and_network_failures(self):
        import httpx
        cases=[(403,[b'{"message":"denied"}'],'denied'),(500,[b'bad'],'暂时无法'),(200,[b'bad'],'暂时不可用'),(200,[b'\x89PNG\r\n\x1a\n',b'x'*(1024*1024)]*21,'暂时不可用')]
        for status,chunks,hint in cases:
            class Response:
                status_code=status
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def aread(self):return b''.join(chunks)
                async def aiter_bytes(self):
                    for chunk in chunks:yield chunk
            class Client:
                def __init__(self,**kwargs):pass
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                def stream(self,method,url,**kwargs):
                    assert method=='POST' and url.endswith('/api/taiko/internal/annual-card')
                    assert kwargs['headers']['X-Taiko-Bot-Token']=='synthetic'
                    return Response()
            with patch.dict(m.os.environ,{'TAIKO_BOT_SERVICE_TOKEN':'synthetic'}),patch.object(m.httpx,'AsyncClient',Client):
                with self.assertRaisesRegex(m.AnnualReportError,hint):asyncio.run(m.fetch_annual_card('qq_official:synthetic'))

    def test_concurrency_cooldown_and_cleanup(self):
        from nonebot.exception import FinishedException
        class Matcher:
            def __init__(self):self.sent=[]
            async def send(self,value):self.sent.append(value)
            async def finish(self,value):self.sent.append(value);raise FinishedException
        async def scenario():
            release=asyncio.Event(); entered=asyncio.Event();calls=[]
            async def fetch(identity):
                calls.append(identity);entered.set();await release.wait();return b'png'
            with patch.object(m,'is_qq_official_event',return_value=True),patch.object(m,'get_identity_key',side_effect=lambda event:event),patch.object(m,'fetch_annual_card',fetch),patch.object(m,'build_report_message',return_value='card'):
                first=Matcher();task=asyncio.create_task(m.handle_annual_report(first,'a'));await entered.wait()
                duplicate=Matcher()
                with self.assertRaises(FinishedException):await m.handle_annual_report(duplicate,'a')
                self.assertIn('正在处理',duplicate.sent[0]);self.assertEqual(calls,['a'])
                m._active.update(('b','c','d'))
                with self.assertRaises(FinishedException):await m.handle_annual_report(Matcher(),'e')
                release.set();await task
                self.assertNotIn('a',m._active);self.assertEqual(first.sent,['card'])
                cooldown=Matcher()
                with self.assertRaises(FinishedException):await m.handle_annual_report(cooldown,'a')
                self.assertIn('频繁',cooldown.sent[0])
        asyncio.run(scenario())

    def test_delivery_fallback_and_api_failure(self):
        from unittest.mock import AsyncMock
        class Matcher:
            def __init__(self,fail=False):self.sent=[];self.fail=fail
            async def send(self,value):
                if self.fail and value=='card':raise RuntimeError('40034128')
                self.sent.append(value)
        async def scenario():
            with patch.object(m,'is_qq_official_event',return_value=True),patch.object(m,'get_identity_key',return_value='q'),patch.object(m,'fetch_annual_card',new=AsyncMock(return_value=b'png')),patch.object(m,'build_report_message',return_value='card'),patch.object(m,'_send_qq_proactive',new=AsyncMock(return_value=True)) as proactive:
                await m.handle_annual_report(Matcher(True),object());self.assertEqual(proactive.await_count,1)
                m._cooldown.clear();proactive.return_value=False
                matcher=Matcher(True);await m.handle_annual_report(matcher,object());self.assertIn('发送失败',matcher.sent[0])
                self.assertFalse(m._active)
            m._cooldown.clear()
            with patch.object(m,'is_qq_official_event',return_value=True),patch.object(m,'get_identity_key',return_value='q'),patch.object(m,'fetch_annual_card',new=AsyncMock(side_effect=m.AnnualReportError('synthetic unavailable'))):
                matcher=Matcher();await m.handle_annual_report(matcher,object());self.assertEqual(matcher.sent,['synthetic unavailable']);self.assertFalse(m._active)
        asyncio.run(scenario())

if __name__ == '__main__': unittest.main()
