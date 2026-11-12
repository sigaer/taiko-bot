import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image
from taiko_application.score.resources import RenderResources
from taiko_application.score.static_resources import StaticImageCache, RequestResources, revision
from taiko_application.score.encoding import to_jpeg_bytes
from taiko_bot.public_catalog_cache import load_public_json, song_index, clear
from taiko_bot.runtime.player.rating_memo import RequestRatingMemo


def test_bounded_images_cannot_mutate_cache_and_revision_invalidates(tmp_path):
    cache=StaticImageCache(128)
    path=tmp_path/'resource.png'
    with Image.new('RGBA',(4,4),'red') as im:im.save(path)
    def load():
        with Image.open(path) as source:return source.convert('RGBA')
    key=(revision(path),None)
    with cache.copy(key,load) as first:first.putpixel((0,0),(0,0,0,0))
    with cache.copy(key,load) as second:assert second.getpixel((0,0))==(255,0,0,255)
    with Image.new('RGBA',(4,4),'blue') as im:im.save(path)
    with cache.copy((revision(path),None),load) as updated:assert updated.getpixel((0,0))==(0,0,255,255)
    for i in range(20):
        with cache.copy(((str(i),0,0),None),load):pass
        assert cache.bytes<=cache.max_bytes
    assert len(cache._items)<=2
    cache.clear();assert cache.bytes==0


def test_static_image_copy_eviction_is_thread_safe(tmp_path):
    cache=StaticImageCache(64)
    def use(i):
        for j in range(20):
            with cache.copy(((str(i),j,0),None),lambda:Image.new('RGBA',(4,4),'green')) as im:
                assert im.getpixel((0,0))==(0,128,0,255)
    with ThreadPoolExecutor(2) as pool:list(pool.map(use,range(2)))
    assert cache.bytes<=64
    cache.clear()


def test_a_real_cache_hit_returns_an_independent_image():
    cache=StaticImageCache(64)
    key=(('public-generated-tile',0,0,0,0),None)
    calls=[]
    def load():calls.append(1);return Image.new('RGBA',(4,4),'red')
    with cache.copy(key,load) as first:first.putpixel((0,0),(0,0,255,255))
    with cache.copy(key,load) as second:assert second.getpixel((0,0))==(255,0,0,255)
    assert len(calls)==1 and cache.bytes==64
    cache.clear()


def test_renderer_exception_releases_owned_images_but_not_borrowed_images():
    caller=Image.new('RGBA',(2,2),'red')
    class Renderer(RenderResources):
        _ICON_CACHE={}
        def _render(self,fail=False):
            self.intermediate=self._own(caller.copy())
            if fail:raise ValueError('synthetic')
            return self._own(caller.copy())
    renderer=Renderer()
    with pytest.raises(ValueError):renderer.render(fail=True)
    with pytest.raises(ValueError):renderer.intermediate.getpixel((0,0))
    with renderer.render() as result:assert result.getpixel((0,0))==caller.getpixel((0,0))
    assert caller.getpixel((0,0))==(255,0,0,255)
    assert renderer._resources is None
    caller.close()


def test_jpeg_preserves_exact_png_roundtrip_and_borrows_caller_image():
    from io import BytesIO
    for mode,color in [('RGBA',(10,20,30,111)),('LA',(12,123)),('RGB',(10,20,30))]:
        with Image.new(mode,(31,17),color) as image:
            with BytesIO() as png:
                image.save(png,format='PNG')
                expected=to_jpeg_bytes(png.getvalue())
            assert to_jpeg_bytes(image)==expected
            assert image.getpixel((0,0))==color


def test_public_catalog_replacement_and_size_change_invalidate(tmp_path):
    clear()
    path=tmp_path/'song_data.json'
    path.write_text('[{"id":1,"song_name":"A"}]')
    first=load_public_json(path)
    assert load_public_json(path) is first
    stamp=path.stat().st_mtime_ns
    path.write_text('[{"id":2,"song_name":"Longer"}]')
    os.utime(path,ns=(stamp,stamp))
    assert list(song_index(path))==[2]
    replacement=tmp_path/'replacement'
    replacement.write_text('[{"id":3,"song_name":"Longer"}]')
    os.utime(replacement,ns=(stamp,stamp));replacement.replace(path)
    assert list(song_index(path))==[3]


def test_rating_memo_is_ordered_revision_bound_and_request_only():
    calls=[];version=[1]
    def calculate(records):calls.append(records);return [dict(r) for r in records]
    memo=RequestRatingMemo(calculate,lambda:version[0])
    records=[{'id':1},{'id':2}]
    assert memo(records)==memo(records) and len(calls)==1
    memo(list(reversed(records)));assert len(calls)==2
    version[0]=2;memo(records);assert len(calls)==3
    RequestRatingMemo(calculate,lambda:version[0])(records);assert len(calls)==4
    for i in range(100):memo([{'id':i}])
    assert len(memo._items)<=32 and memo._records<=32000
    aggregations=[]
    aggregate=memo.aggregate('sum',lambda values,n:aggregations.append(n) or sum(values[:n]))
    values=[1,2,3]
    assert aggregate(values,2)==aggregate(values,2)==3 and aggregations==[2]
    assert aggregate(values,3)==6 and aggregations==[2,3]
    assert aggregate(list(values),2)==3 and aggregations==[2,3,2]


def test_precomputed_v1_requires_matching_profile_deduplication_and_catalog(tmp_path,monkeypatch):
    from taiko_bot.runtime.player.prepared_rating import prepare_v1_results,reusable_v1_results
    (tmp_path/'songs').mkdir()
    (tmp_path/'songs/rating_structured_with_ids.json').write_text('{}')
    song=tmp_path/'songs/song_data.json';song.write_text('[]')
    monkeypatch.chdir(tmp_path)
    result=prepare_v1_results(lambda:[1,2],profile='center',collapse=True,song_path=song,user_id='synthetic',records=[1,2])
    def reusable(value=result,**options):
        return reusable_v1_results(value,**dict(dict(profile='center',collapse=True,user_id='synthetic',records=[1,2]),**options))
    assert reusable()
    assert not reusable(profile='client')
    assert not reusable(collapse=False)
    assert not reusable(user_id='another-user')
    assert not reusable(records=[2,1])
    assert not reusable([1,2])
    song.write_text('[1]')
    assert not reusable()
