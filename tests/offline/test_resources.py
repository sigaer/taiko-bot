import hashlib,json
from pathlib import Path
import pytest
from taiko_bot.cli.resources import verify,materialize

def fixture(root):
 store=root/'private';(store/'objects').mkdir(parents=True)
 payload=b'synthetic resource';digest=hashlib.sha256(payload).hexdigest();(store/'objects'/digest).write_bytes(payload)
 manifest=root/'manifest.json';manifest.write_text(json.dumps({'entries':[{'path':'songs/test.json','sha256':digest,'bytes':len(payload)}]}))
 return store,manifest,digest

def test_content_checked_install_and_idempotent_reuse(tmp_path):
 store,manifest,digest=fixture(tmp_path);destination=tmp_path/'runtime'
 assert materialize(manifest,store,destination)=={'verified':1,'written':1}
 assert hashlib.sha256((destination/'songs/test.json').read_bytes()).hexdigest()==digest
 assert materialize(manifest,store,destination)=={'verified':1,'written':0}
 (destination/'songs/test.json').write_text('changed')
 with pytest.raises(ValueError):materialize(manifest,store,destination)
 assert (destination/'songs/test.json').read_text()=='changed'

def test_corrupt_source_and_traversal_do_not_write(tmp_path):
 store,manifest,digest=fixture(tmp_path);destination=tmp_path/'runtime'
 (store/'objects'/digest).write_text('corrupt')
 with pytest.raises(ValueError):materialize(manifest,store,destination)
 assert not destination.exists()
 payload=json.loads(manifest.read_text());payload['entries'][0]['path']='../outside';manifest.write_text(json.dumps(payload))
 with pytest.raises(ValueError):verify(manifest,store)
