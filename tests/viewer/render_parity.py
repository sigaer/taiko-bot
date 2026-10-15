"""Run captured host fixtures, then compare Viewer PNGs to frozen implementations.

Use the bounded QA runner. --family selects the checked-in fixture; all remaining
arguments are its existing isolated CLI (synthetic assets, frozen public source).
"""
import argparse
import hashlib
import os
from pathlib import Path
import runpy
import sys

parser=argparse.ArgumentParser(add_help=False)
parser.add_argument('--family',choices=('b30','progress','personal','trend','recommendation'),required=True)
args,rest=parser.parse_known_args()
fixture=Path(__file__).resolve().parents[1]/args.family/'events.py'
sys.path.insert(0,str(fixture.parent))
sys.argv=[str(fixture),*rest]
ns=runpy.run_path(str(fixture),run_name='__main__')
os.environ['TAIKO_OFFLINE_ROOT']=str(ns['a'].work)
os.environ['TAIKO_RUNTIME_ROOT']=str(ns['a'].work)
from taiko_bot.offline import viewer
if 'clock' in ns:viewer.datetime=ns['clock']


def digest(value):
    data=value.getvalue() if hasattr(value,'getvalue') else value
    assert isinstance(data,bytes) and data.startswith(b'\x89PNG'), 'Expected successful PNG'
    return hashlib.sha256(data).hexdigest()


if args.family=='b30':
    score=ns['old_score'];summary=ns['old_summary'];dimension=ns['old_dimension']
    cases=[
        ('b30',lambda:summary.render_b30_image(111,N=30),lambda:viewer.render_b30_image(111,N=30)),
        ('dimension',lambda:dimension.generate_dim_top_image(score.compute_all_from_userdata(111),20,'精度',user_id=111),lambda:viewer.generate_dim_top_image(viewer.compute_all_from_userdata(111),20,'精度',user_id=111)),
        ('radar',lambda:score.generate_top_N_image(score.compute_all_from_userdata(111),20,user_id=111),lambda:viewer.generate_top_N_image(viewer.compute_all_from_userdata(111),20,user_id=111)),
    ]
elif args.family=='progress':
    render=ns['old_render'];dan=ns['old_dani']
    cases=[]
    for name,value in [('render_pass_progress_image_bytes','9.0'),('render_progress_image_bytes','9.0'),('render_star_progress_image_bytes',9),('render_progress_image_bytes_by_list','SS')]:
        cases.append((name,lambda name=name,value=value:getattr(render,name)(111,value),lambda name=name,value=value:getattr(viewer,name)(111,value)))
    cases.append(('dani',lambda:dan.render_dani_progress_image_bytes(111,'六段'),lambda:viewer.render_dani_progress_image_bytes(111,'六段')))
elif args.family=='trend':
    cases=[('trend',lambda:ns['old_score'].generate_rating_trend_image(111),lambda:viewer.generate_rating_trend_image(111))]
elif args.family=='recommendation':
    old=ns['old_calc']
    expected_recs=old.compute_recommendations_for_user(111,best_key='rating',limit=10)
    actual_recs=viewer.compute_recommendations_for_user(111,best_key='rating',limit=10)
    assert expected_recs==actual_recs, 'Recommendation JSON mismatch'
    cases=[('recommendation',lambda:old.generate_recommend_image(expected_recs,user_id=111,font_path='assets/fonts/DDFont.ttf'),lambda:viewer.generate_recommend_image(actual_recs,user_id=111,font_path='assets/fonts/DDFont.ttf'))]
else:
    from taiko_bot.runtime.player.center import custom_title
    custom_title.get_taiko_db_connection=ns['connection']
    custom_title._schema_ready=True
    cases=[('mydon',lambda:ns['old_dress'].render_my_don_image(111),lambda:viewer.render_my_don_image(111)),
           ('cloud',lambda:ns['old_cloud'].render_tcloud_image(111),lambda:viewer.render_tcloud_image(111))]
for name,before,after in cases:
    assert digest(before())==digest(after()), name+' PNG mismatch'
    print('Viewer frozen '+name+' PNG PASS',flush=True)
assert not ns['violations'],ns['violations']
