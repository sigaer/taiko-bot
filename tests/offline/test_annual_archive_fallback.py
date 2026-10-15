import os,sys,types,json,tempfile,unittest
from pathlib import Path
from datetime import datetime
os.environ['TAIKO_COMPUTE_ONLY']='1'

from taiko_bot.offline.annual_summary.service import build_annual_result
class ArchiveTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir='/var/tmp');self.root=Path(self.tmp.name);(self.root/'123').mkdir();self.song=self.root/'songs.json';self.song.write_text('{}')
 def tearDown(self):self.tmp.cleanup()
 def put(self,day,songs=True,source='wahlap'):
  p={'_meta':{'full':True,'source':source,'observed_at':day+'T12:00:00'},'profile':{'mydon_name':'QA'},'songs':[{'song_no':1318,'level':4,'stage_cnt':10,'high_score':800000,'clear_cnt':1,'good_cnt':500,'ok_cnt':5,'bad_cnt':0}] if songs else []}
  (self.root/'123'/('data_'+day+'_'+source+'.json')).write_text(json.dumps(p))
 def build(self,enabled=False):return build_annual_result('123',{'key':'annual_2026','startDate':'2025-10-09','endDate':'2026-09-30','endExclusive':'2026-10-01','timezone':'Asia/Shanghai','reportRevision':'annual-report-2026-r2-final-window'},userdata_dir=self.root,song_data_path=self.song,rating_path=None,generated_at=datetime(2026,10,2),allow_current_archive=enabled)
 def test_new_account_requires_opt_in(self):
  self.put('2026-10-01')
  with self.assertRaisesRegex(ValueError,'no snapshots in annual window'):self.build()
  r=self.build(True);s=r['summary'];self.assertEqual(s['mode'],'current_archive');self.assertEqual(r['events'],[]);self.assertEqual(s['overview']['data']['playCount'],10);self.assertEqual(s['version']['endDate'],'2026-09-30');self.assertTrue(any(x.startswith('current_archive_fallback:') for x in s['provenance']['warnings']))
  for key in ['highScore','challenge','milestones','weekdayActivity','monthlyFavorites']:self.assertEqual(s['sections'][key]['status'],'unavailable')
 def test_existing_annual_is_identical(self):
  self.put('2026-09-01');self.assertEqual(self.build(),self.build(True))
 def test_empty_current_still_rejected(self):
  self.put('2026-10-01',False)
  with self.assertRaises(ValueError):self.build(True)
 def test_import_changes_identity_even_outside_window(self):
  self.put('2026-09-01');before=self.build()['summary']['summaryId'];self.put('2026-10-01',source='kinoko-import');self.assertNotEqual(before,self.build()['summary']['summaryId'])
if __name__ == "__main__":
 unittest.main()
