"""Deterministic, entirely synthetic B30 profiles over a frozen public catalog."""
import copy
import datetime as dt
import hashlib
import json
import random
import shutil
from pathlib import Path

SEED = 20261112
NOW = '2026-11-11T12:00:00'
DESCRIPTIONS = ['无成绩', '少量成绩', '不满Top20', '不满Top30', '满Top30',
                '满Top50', '中等成绩量', '高密度成绩量', '重复歌曲版本', '无历史',
                '正常30天历史', '长期全量及增量历史', 'u0多账号合并', '长曲名多语言复杂装扮']
COUNTS = [0, 3, 17, 27, 30, 50, 350, 1800, 90, 80, 100, 350, 150, 50]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root, public):
    root, public = Path(root), Path(public)
    root.mkdir(parents=True, exist_ok=True)
    (root/'songs').mkdir(exist_ok=True)
    for name in ['song_data.json', 'rating_structured_with_ids.json', 'constants_id_v2.csv',
                 'song_alias.json', 'song_merged.json', 'song_title.json', 'song_removed.json',
                 'roll_note_count.json', 'song_visibility.json']:
        source = public/'songs'/name
        if source.exists():
            shutil.copyfile(source, root/'songs'/name)
    # Public assets are permitted, and contain no player configuration or scores.
    (root/'assets').symlink_to(public/'assets', target_is_directory=True)
    cfg = json.loads((root/'songs/rating_structured_with_ids.json').read_text())
    songs = json.loads((root/'songs/song_data.json').read_text())
    song_by_id = {int(s['id']): s for s in songs}
    charts = [c for c in cfg['songs'].values() if int(c.get('level', 0)) >= 4 and int(c.get('id',0)) in song_by_id]
    rng = random.Random(SEED)
    rng.shuffle(charts)
    metadata = []
    (root/'fixtures').mkdir(exist_ok=True)
    for i, (description, count) in enumerate(zip(DESCRIPTIONS, COUNTS), 1):
        records = []
        for j, chart in enumerate(charts[:count]):
            sid, level = int(chart['id']), int(chart['level'])
            song = song_by_id[sid]
            combos = song.get('max_combo', [0]*5)
            total = int((combos[level-1] if isinstance(combos, list) and len(combos) >= level else 600) or 600)
            accuracy = rng.choice([0.60, 0.76, 0.82, 0.91, 0.96, 0.99, 1.0]) if i >= 7 else rng.uniform(.91,1.0)
            good = round(total*accuracy)
            bad = 0 if accuracy > .98 else rng.randrange(0, max(1,total//50))
            ok = max(0,total-good-bad)
            records.append(dict(song_no=sid, level=level, high_score=round(500000+accuracy*690000),
                good_cnt=good, ok_cnt=ok, ng_cnt=bad, pound_cnt=j%101, combo_cnt=total-bad,
                clear_cnt=1, full_combo_cnt=int(bad==0), dondaful_combo_cnt=int(good==total),
                best_score_rank=1+j%8, option_flg=[1.0+(j%3)*.5, j%2, (j//2)%2, '10'], stage_cnt=2))
        if i == 9:
            # Same chart repeated with a lower high score; distinct catalog IDs also retained.
            records += [dict(r, high_score=r['high_score']-100) for r in records[:20]]
        payload = dict(profile=dict(name='合成プレイヤー Synthetic Ω' if i==14 else f'Synthetic U{i:02}',
                                   title='测试用称号', mydon={}), achievement={}, dojo={}, songs=records)
        history=[]
        days = 30 if i==11 else 180 if i==12 else 0
        for day in range(days):
            stamp = dt.datetime.fromisoformat(NOW)-dt.timedelta(days=days-day)
            previous = [dict(r, good_cnt=max(0,r['good_cnt']-(days-day)%9),
                             ok_cnt=r['ok_cnt']+(days-day)%9) for r in records]
            full = day==0 or day%30==0
            blob = dict(payload, songs=previous, _meta={'full':True}) if full else {'_meta':{'full':False},'songs':previous[:max(1,len(previous)//10)]}
            history.append(dict(capturedAt=stamp.isoformat(), fileName=f'data_{stamp:%Y%m%d_%H%M%S_000000}.json',
                                historyFormat='raw-v1', payload=blob))
        fixture=dict(id=f'U{i:02}', description=description, current=payload, history=history,
                     members=[dict(payload,songs=records[::2]),dict(payload,songs=records[1::2])] if i==13 else [])
        path=root/'fixtures'/f'U{i:02}.json'
        path.write_text(json.dumps(fixture,ensure_ascii=False))
        metadata.append(dict(id=fixture['id'],description=description,records=len(records),snapshots=len(history),sha256=sha(path)))
    resources={str(p.relative_to(public)):sha(p) for p in sorted((public/'assets').rglob('*')) if p.is_file()}
    manifest=dict(seed=SEED,now=NOW,synthetic=True,users=metadata,
                  catalog={p.name:sha(p) for p in (root/'songs').iterdir()},assets=resources)
    (root/'fixture-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest


def finalize(root, public):
    """Pin only rendering resources, and complete two untimed edge fixtures."""
    root, public = Path(root), Path(public)
    assets = root/'assets'
    if assets.is_symlink():
        assets.unlink()
        assets.mkdir()
        for name in ('cover','dress','templates','fonts','icons','name_plate','name_plate_dani'):
            if (public/'assets'/name).exists():
                shutil.copytree(public/'assets'/name,assets/name)
    cfg=json.loads((root/'songs/rating_structured_with_ids.json').read_text())
    songs=json.loads((root/'songs/song_data.json').read_text())
    by_id={int(s['id']):s for s in songs}
    path=root/'fixtures/U09.json'
    fixture=json.loads(path.read_text())
    for chart in cfg['songs'].values():
        song=by_id.get(int(chart['id']),{})
        if int(chart['level'])>=4 and song.get('legacy_ids'):
            record=dict(fixture['current']['songs'][0],song_no=int(chart['id']),level=int(chart['level']))
            fixture['current']['songs'] += [record,dict(record,song_no=int(song['legacy_ids'][0]),high_score=record['high_score']-100)]
            break
    path.write_text(json.dumps(fixture,ensure_ascii=False))
    path=root/'fixtures/U14.json'
    fixture=json.loads(path.read_text())
    charts=sorted((c for c in cfg['songs'].values() if int(c.get('level',0))>=4 and int(c['id']) in by_id),
                  key=lambda c:len(str(by_id[int(c['id'])].get('song_name_jp',''))),reverse=True)
    for record,chart in zip(fixture['current']['songs'],charts):
        record.update(song_no=int(chart['id']),level=int(chart['level']))
    fixture['current']['profile']['gameCostume']=dict(costume_1=0,costume_2=144,costume_3=127,costume_4=0,costume_5=188,
        color_face=0,color_body=1,color_limb=3,mydon_name='合成プレイヤー Synthetic Ω',title='长称号・日本語・English テスト',titleplate_id=0)
    path.write_text(json.dumps(fixture,ensure_ascii=False))
    manifest=json.loads((root/'fixture-manifest.json').read_text())
    for user in manifest['users']:
        path=root/'fixtures'/f'{user["id"]}.json'
        fixture=json.loads(path.read_text())
        user.update(sha256=sha(path),records=len(fixture['current']['songs']))
    manifest['assets']={str(p.relative_to(root)):sha(p) for p in sorted(assets.rglob('*')) if p.is_file()}
    (root/'fixture-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return dict(users=manifest['users'],assetFiles=len(manifest['assets']))


def extras(root):
    root=Path(root)
    from sakura_taiko_core.parser.v2_dataset import parse_v2_dataset_csv
    snapshot=parse_v2_dataset_csv((root/'songs/constants_id_v2.csv').read_text(),loaded_at_monotonic=0)
    base=json.loads((root/'fixtures/U05.json').read_text())
    hard=[chart for (_,level),chart in sorted(snapshot.song_map.items()) if level==3 and chart.total_notes>0][:6]
    records=[]
    for chart in hard:
        total=int(chart.total_notes)
        good=int(total*.98)
        records.append(dict(base['current']['songs'][0],song_no=int(chart.song_id),level=3,
                            good_cnt=good,ok_cnt=total-good,ng_cnt=0,dondaful_combo_cnt=0))
    assert records,'The pinned catalog must contain level 3 charts'
    records += [dict(records[0],level=1),dict(records[0],level=2)]
    manifest=[]
    for uid,description,scores in [('E01','仅简单普通困难，无鬼成绩',records),
          ('E02','五种难度混合',base['current']['songs']+records),
          ('E03','鬼难度均低于75%良率',[dict(r,good_cnt=1,ok_cnt=1000,ng_cnt=0,dondaful_combo_cnt=0) for r in base['current']['songs']])]:
        value=copy.deepcopy(base)
        value.update(id=uid,description=description,members=[],history=[])
        value['current']['songs']=scores
        path=root/'fixtures'/f'{uid}.json';path.write_text(json.dumps(value,ensure_ascii=False))
        manifest.append(dict(id=uid,description=description,sha256=sha(path),records=len(scores)))
    (root/'edge-fixture-manifest.json').write_text(json.dumps(dict(seed=SEED,now=NOW,users=manifest),ensure_ascii=False,indent=2))
    return manifest


def verify(root):
    """Verify the frozen inputs without consulting any production player data."""
    root=Path(root)
    manifest=json.loads((root/'fixture-manifest.json').read_text())
    for user in manifest['users']:
        assert sha(root/'fixtures'/f'{user["id"]}.json')==user['sha256'],user['id']
    for name,digest in manifest['catalog'].items():assert sha(root/'songs'/name)==digest,name
    for name,digest in manifest['assets'].items():assert sha(root/name)==digest,name
    edge=root/'edge-fixture-manifest.json'
    if edge.exists():
        for user in json.loads(edge.read_text())['users']:
            assert sha(root/'fixtures'/f'{user["id"]}.json')==user['sha256'],user['id']
    return dict(status='PASS',users=len(manifest['users']),assets=len(manifest['assets']))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['prepare','finalize','extras','verify'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--public',type=Path)
    args=parser.parse_args()
    if args.operation=='prepare':
        assert not args.root.exists(),'Refusing to overwrite an existing frozen corpus'
        result=prepare(args.root,args.public)
    elif args.operation=='finalize':result=finalize(args.root,args.public)
    elif args.operation=='extras':result=extras(args.root)
    else:result=verify(args.root)
    print(json.dumps(result if args.operation!='prepare' else {'users':result['users']},ensure_ascii=False))
