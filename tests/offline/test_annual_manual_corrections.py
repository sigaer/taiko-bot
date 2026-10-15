import sys,types,importlib.machinery,unittest,os
os.environ["TAIKO_COMPUTE_ONLY"]="1"
from pathlib import Path
from datetime import datetime

from taiko_bot.offline.annual_summary.corrections import reconcile_manual_corrections
from taiko_bot.offline.annual_summary.model import RebuiltSnapshot,SnapshotHistory,WindowSelection
from taiko_bot.offline.annual_summary.aggregates import build_static_personality_sections,build_achievements_and_breakthrough,build_overview,build_time_sections

def state(day,source,**fields):
 d=dict(stage_cnt=10,high_score=1000,full_combo_cnt=1,clear_cnt=1,best_score_rank=8);d.update(fields)
 return RebuiltSnapshot(Path(str(day)),datetime(2026,9,day),{'songs':[dict(song_no=1,level=4,**d)]},source,'a',[],str(day),changed_keys=((1,4),))
def event(kind='play_delta',day=2,**after):
 d=dict(stage_cnt=10,high_score=1000,best_score_rank=8);d.update(after)
 return dict(eventId=kind+str(day),type=kind,songNo=1,level=4,observedBetween={'to':f'2026-09-{day:02d}T00:00:00+08:00'},after=d,before={'best_score_rank':0},delta={'playCount':5,'fullComboUnlocked':True,'clearUnlocked':True},warnings=[],representativeAt=f'2026-09-{day:02d}T00:00:00+08:00',timePrecision='source_highscore_time' if kind=='high_score' else 'batch_last_play_proxy')
def run(events,history,window=None):
 w=window or history;s=WindowSelection(w,w,w[0],w[0].state,w[-1].state,True,datetime(2026,9,30).date())
 return reconcile_manual_corrections(events,s,SnapshotHistory(history,[]))
class Corrections(unittest.TestCase):
 def test_score_reset_preserves_plays_and_future_records(self):
  history=[state(1,'wahlap'),state(3,'web-account',high_score=0),state(4,'wahlap',high_score=1100)]
  events=[event(),event('high_score'),event('high_score',4,high_score=1100)]
  out,s,w=run(events,history);self.assertEqual([x['eventId'] for x in out],['play_delta2','high_score4']);self.assertEqual(events[0]['delta']['fullComboUnlocked'],True)
 def test_achievements_rank_retracted_not_plays(self):
  out,s,w=run([event()],[state(1,'wahlap'),state(3,'web-account',full_combo_cnt=0,clear_cnt=0,best_score_rank=0)])
  self.assertFalse(out[0]['delta']['fullComboUnlocked']);self.assertFalse(out[0]['delta']['clearUnlocked']);self.assertEqual(out[0]['delta']['playCount'],5);self.assertIn('manual_correction_invalidates:best_score_rank',out[0]['warnings'])
  a,b=build_achievements_and_breakthrough(out,s.start_state,s.end_state,{1:{'level_4':10}});self.assertEqual(a['observedUnlocks']['full_combo']['count'],0);self.assertEqual(b['status'],'unavailable')
 def test_lower_play_count_excludes_unlocatable_batch(self):
  out,_,_=run([event()],[state(1,'wahlap'),state(3,'web-account',stage_cnt=0)]);self.assertEqual(out,[])
 def test_lock_only_and_official_regression_unchanged(self):
  for source in ['wahlap','web-account']:
   h=[state(1,'wahlap'),state(3,source,**({'high_score':0} if source=='wahlap' else {}))];e=[event('high_score')];out,_,_=run(e,h);self.assertEqual(out,e)
 def test_manual_import_and_post_window_correction(self):
  old=state(1,'wahlap');last=state(3,'web-score-import',high_score=0,stage_cnt=20);out,s,_=run([event('high_score')],[old,last],[old]);self.assertEqual(out,[]);self.assertEqual(s.end_state['songs'][0]['high_score'],0);self.assertEqual(s.end_state['songs'][0]['stage_cnt'],10);self.assertEqual(old.state['songs'][0]['high_score'],1000)
 def test_score_edit_does_not_change_unrelated_chart(self):
  e=event('high_score');e['songNo']=2;out,_,_=run([e],[state(1,'wahlap'),state(3,'manual-score',high_score=0)]);self.assertEqual(out,[e])
 def test_manual_timestamp_does_not_inherit_last_sync(self):
  import tempfile,json
  from taiko_bot.offline.annual_summary.snapshots import _read_snapshot_plan_entry
  with tempfile.TemporaryDirectory(prefix='annual-manual-time-',dir='/var/tmp') as directory:
   p=Path(directory)/'data_2026-09-03_12_00_00_web-account.json';p.write_text(json.dumps({'_meta':{'full':True,'source':'web-account','ts':'2026-09-03 12:00:00','observed_at':'2026-09-01T00:00:00','synced_at':'2026-09-01T00:00:00'},'songs':[]}))
   self.assertEqual(_read_snapshot_plan_entry(p).observed_at,datetime(2026,9,3,12))
 def test_deleted_manual_chart_retracts_old_events(self):
  from dataclasses import replace
  old=state(1,'wahlap');deleted=replace(state(3,'manual-score-delete'),state={'songs':[]})
  out,s,_=run([event(),event('high_score')],[old,deleted],[old]);self.assertEqual(out,[]);self.assertEqual(s.end_state['songs'],[])
if __name__=='__main__':unittest.main()
