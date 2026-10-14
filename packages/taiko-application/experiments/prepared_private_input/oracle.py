"""Execute the pre-extraction tinfo body, without importing a bot or storage."""
import ast
import asyncio
import hashlib
import json
import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from .render_fixture import render, query


class Finish(BaseException):
    pass


def error_result(error):
    # Pillow includes a per-object address in this one exception message.
    message = str(error)
    if type(error).__name__ == 'UnidentifiedImageError':
        message = re.sub(r'(?<=<_io.BytesIO object at )0x[0-9a-f]+(?=>)', '<address>', message)
    return {'raised': type(error).__name__, 'message': message}


def canonical(result):
    if result.kind == 'image':
        with Image.open(BytesIO(result.payload)) as image:
            image.load()
            return {'kind':'image','sha256':hashlib.sha256(result.payload).hexdigest(),
                    'pixels':hashlib.sha256(image.tobytes()).hexdigest(),
                    'size':list(image.size),'mode':image.mode,'prefix':result.prefix_text}
    return {'kind':result.kind,'text':result.payload,'delivery':result.delivery}


def run_legacy(host, text, failure=None):
    frozen = Path(__file__).with_name('frozen_tinfo.py.txt').read_text()
    record = json.loads(Path(__file__).with_name('provenance.json').read_text())
    assert hashlib.sha256(frozen.encode()).hexdigest() == record['selected_sha256']
    outputs=[]
    class Matcher:
        async def finish(self, value):
            outputs.append({'kind':'text','text':value,'delivery':'direct'})
            raise Finish()
    async def reply(matcher,event,value):
        outputs.append({'kind':'text','text':value,'delivery':'reply'})
        raise Finish()
    async def image(matcher,event,value,**kw):
        outputs.append(canonical(SimpleNamespace(kind='image',payload=value,prefix_text=kw.get('prefix_text',''))))
        raise Finish()
    def generate(*, song_no, user_id, prefer_best_in_group):
        assert prefer_best_in_group is True
        return render(host.legacy_read(user_id), song_no, failure)
    def resolve(event):
        try:
            return {'user_id':host.observe().user_id}
        except RuntimeError as error:
            return {'error':str(error)}
    ns={'re':re,'BytesIO':BytesIO,'Image':Image,'music_info':Matcher(),
        '_resolve_read_bind_target_safe':resolve, '_taiko_bind_usage_message':lambda e:'fixture bind help',
        '_extract_music_info_command_match':lambda e:re.fullmatch(r'^/?tinfo\s?(.+)$',e.text),
        '_finish_text_reply':reply,'_finish_image_reply':image,
        'generate_score_image':generate,'queryMusic':query,'print':lambda *a:None,
        'FUZZY_ACCEPT_THRESHOLD':0.7,'is_accepted_similarity':lambda ratio,threshold:float(ratio)/100>=threshold}
    tree=ast.parse('from __future__ import annotations\n'+frozen)
    exec(compile(tree,'<frozen-tinfo>','exec'),ns)
    async def run():
        try:
            await ns['music_info_handle'](SimpleNamespace(text=text))
        except Finish:
            pass
    try:
        asyncio.run(run())
    except Exception as e:
        return error_result(e)
    assert len(outputs)==1
    return outputs[0]
