import hashlib
import pytest
from taiko_bot.offline.catalog_downloads import download_file, catalog_resource_root
from taiko_bot.offline.catalog_images import image_plan
from taiko_bot.offline.catalog_resources import single_levels


class Response:
    status_code=200
    def __init__(self,data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def raise_for_status(self): pass
    def iter_content(self,size): yield self.data


class Session:
    def __init__(self,data): self.data=data;self.calls=0
    def get(self,*args,**kwargs): self.calls+=1;return Response(self.data)


def descriptor(data):
    sha=hashlib.sha256(data).hexdigest()
    return {'sha256':sha,'size':len(data),'url':'https://distrib.ourtaiko.org/database/'+sha+'.tja'}


def test_remote_resource_integrity_and_resumable_cache(tmp_path):
    data=b'TITLE:Test\n';session=Session(data);path=tmp_path/'test.tja'
    assert download_file(descriptor(data),path,maximum=100,session=session)==path
    assert path.read_bytes()==data and session.calls==1
    download_file(descriptor(data),path,maximum=100,session=session)
    assert session.calls==1
    with pytest.raises(ValueError,match='integrity'):
        download_file(descriptor(data),tmp_path/'bad.tja',maximum=100,session=Session(b'x'*len(data)))
    assert not (tmp_path/'bad.tja').exists() and not list(tmp_path.glob('.download-*'))


def test_remote_manifest_rejects_untrusted_hosts_and_oversized_objects(tmp_path):
    source=descriptor(b'abc');source['url']=source['url'].replace('distrib.ourtaiko.org','example.invalid')
    with pytest.raises(ValueError,match='manifest'):download_file(source,tmp_path/'x',maximum=10,session=Session(b'abc'))
    with pytest.raises(ValueError,match='manifest'):download_file(descriptor(b'abc'),tmp_path/'x',maximum=2,session=Session(b'abc'))


def test_image_plan_resolves_remote_sources_and_keeps_player_sides_separate(tmp_path):
    ese=tmp_path/'ese';ese.mkdir()
    source=tmp_path/'assets/catalog_sources/ourtaiko/a/chart.tja';source.parent.mkdir(parents=True);source.write_text('test')
    song={'id':101619,'resource_source':'ourtaiko','tja_path':'a/chart.tja','song_name':'中文曲名','song_name_jp':'Tomare',
          'ourtaiko_difficulties':[{'difficulty':4,'side':'p1','level':8},{'difficulty':4,'side':'p2','level':8}]}
    plan=image_plan([song],root=tmp_path,ese_root=ese)
    assert {r['side'] for r in plan['jobs']}=={'p1','p2'}
    assert {r['tja'] for r in plan['jobs']}=={str(source)}
    assert {r['output'].split('/')[-1] for r in plan['jobs']}=={'101619-p1.png','101619-p2.png'}
    assert {r['title'] for r in plan['jobs']}=={'中文曲名 [P1]','中文曲名 [P2]'}
    assert not plan['issues']
    output=tmp_path/'assets/fumens/Oni/101619-p1.png';output.parent.mkdir(parents=True);output.write_bytes(b'original')
    again=image_plan([song],root=tmp_path,ese_root=ese)
    assert len(again['jobs'])==1 and again['jobs'][0]['side']=='p2' and output.read_bytes()==b'original'


def test_single_course_after_double_does_not_inherit_style():
    text='COURSE:Oni\nLEVEL:8\nSTYLE:Double\n#START P1\n1111,\n#END\nCOURSE:Hard\nLEVEL:5\n#START\n1111,\n#END\n'
    assert single_levels(text)=={3:5}


def test_failed_image_archive_keeps_retry_marker(tmp_path, monkeypatch):
    from taiko_bot.offline import catalog_images
    marker=tmp_path/catalog_images.ARCHIVE_MARKER
    assert catalog_images.publish_image_archives(root=tmp_path) is False
    marker.parent.mkdir(parents=True);marker.write_text('{"pending":true}')

    class Process:
        pid=123
        returncode=1
        def communicate(self,timeout): return '', 'failed archive'

    monkeypatch.setattr(catalog_images.subprocess,'Popen',lambda *a,**k:Process())
    monkeypatch.setattr(catalog_images.os,'killpg',lambda *a:None)
    with pytest.raises(RuntimeError,match='archives failed'):
        catalog_images.publish_image_archives(root=tmp_path)
    assert marker.is_file()
    Process.returncode=0
    assert catalog_images.publish_image_archives(root=tmp_path) is True
    assert not marker.exists()


def test_optional_static_mirror_failure_does_not_block_catalog(monkeypatch, tmp_path):
    import subprocess
    from taiko_bot.offline import catalog_publication
    def failed(*args,**kwargs):
        assert kwargs['timeout']==30
        raise subprocess.CalledProcessError(1,['ossutil'])
    monkeypatch.setattr(catalog_publication.subprocess,'run',failed)
    assert catalog_publication.sync_public_mirror(tmp_path/'song_data.json','oss://synthetic/song_data.json') is False
