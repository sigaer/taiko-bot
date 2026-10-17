import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cover_upload',ROOT/'taiko_bot/runtime/community/cover_upload.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class CoverUpload(unittest.TestCase):
 def test_derivatives_retry_and_partial_failure(self):
  with tempfile.TemporaryDirectory(dir=__import__('os').environ['QA_RUN_TMPDIR']) as root:
   original=Path(root)/'1529.png'
   with Image.new('RGB',(400,400),'blue') as im:im.save(original)
   digest=hashlib.sha256(original.read_bytes()).hexdigest();commands=[]
   def upload(args,**kw):
    commands.append(args)
    if '/200/' in args[4]:raise RuntimeError('controlled failure')
   with patch.object(module.subprocess,'run',side_effect=upload):ok,detail=module.upload_cover(original)
   self.assertFalse(ok);self.assertIn('原图已同步',detail);self.assertIn('重试',detail);self.assertEqual(len(commands),3)
   with patch.object(module.subprocess,'run'):self.assertTrue(module.upload_cover(original)[0])
   self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),digest)
   for size in (200,400):
    with Image.open(Path(root)/'thumb'/str(size)/'1529.webp') as im:self.assertEqual(im.size,(size,size));self.assertEqual(im.format,'WEBP')

 def test_both_command_handlers_retry_existing_png(self):
  import ast
  for role in ('center','client'):
   source=(ROOT/f'taiko_bot/runtime/community/{role}/cover.py').read_text();ast.parse(source)
   self.assertIn('await asyncio.to_thread(_upload_cover_to_oss, save_path)',source)
   self.assertNotIn('若要更换请先删除旧文件',source)

if __name__=='__main__':unittest.main()
