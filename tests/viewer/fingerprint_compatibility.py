import hashlib,json,os,subprocess,tempfile,shutil
from pathlib import Path
import argparse
p=argparse.ArgumentParser();p.add_argument('--sakura', type=Path, required=True);args=p.parse_args()
from taiko_bot.offline.fingerprint import artifact_identity,growth_revision
import taiko_bot.offline.fingerprint as mod
manifest=json.loads((Path(mod.__file__).parent/'growth-compatibility.dat').read_text())
assert artifact_identity()==manifest['artifactIdentity'], 'Compatibility must bind installed content'
root=Path(tempfile.mkdtemp(dir='/var/tmp',prefix='revision-'))
try:
 (root/'songs').mkdir()
 for name,value in [('rating_structured_with_ids.json','{"songs":{}}'),('song_data.json','[]'),('song_alias.json','[]')]:
  (root/'songs'/name).write_text(value)
 expected=hashlib.sha256()
 for name in manifest['legacyFiles']:
  raw=subprocess.check_output(['git','-C',str(args.sakura),'show',f"{manifest['legacyCommit']}:taiko/{name}"])
  expected.update(name.encode()+b'\0'+raw+b'\0')
 for name in ['songs/rating_structured_with_ids.json','songs/song_data.json','songs/song_alias.json']:
  expected.update(name.encode()+b'\0'+(root/name).read_bytes()+b'\0')
 before=growth_revision(root)
 assert before==expected.hexdigest(), 'Frozen complete legacy revision differs'
 relocated=root/'relocated';shutil.copytree(root/'songs',relocated/'songs')
 assert growth_revision(relocated)==before
 path=root/'songs/song_data.json';info=path.stat();path.write_text('{}');os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
 assert growth_revision(root)!=before,'Same-size preserved-mtime input change must invalidate'
 original=mod.artifact_identity;mod.artifact_identity=lambda:'a'*64
 try:assert growth_revision(relocated)!=before,'Algorithm change must invalidate'
 finally:mod.artifact_identity=original
 print('Growth full legacy hash, relocation continuity, same-stat input change, algorithm invalidation: PASS')
finally:shutil.rmtree(root)
