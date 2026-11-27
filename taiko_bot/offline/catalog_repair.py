"""Stage and publish a bounded public catalog repair, preserving private data."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

from .catalog_chart_sync import reconcile_charts, catalog_changes
from .catalog_constants import fill_constants
from .catalog_images import queue_chart_images
from .catalog_resources import enrich_resources
from .ourtaiko_catalog import atomic_json, fetch_charts, merge_catalog

FILES = ('song_data.json','song_id2tjapath.json','taiko_song_database.json','ourtaiko_charts.json',
         'catalog_constants.json','constants_id_v2.csv','rating_structured_with_ids.json','taiko_goku_onis.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root, stage, *, ese_root, calculator, refresh=False):
    directory = stage / 'songs'
    directory.mkdir(parents=True, exist_ok=False)
    original = {}
    for name in FILES:
        path = root/'songs'/name
        original[name] = digest(path)
        shutil.copy2(path,directory/name)
    atomic_json(stage/'original.json', original)
    # Shared assets are read by the calculator, never copied into the repair.
    (stage/'assets').symlink_to(root/'assets', target_is_directory=True)
    songs = json.loads((directory/'song_data.json').read_text())
    wiki = json.loads((directory/'taiko_song_database.json').read_text())
    charts = json.loads((directory/'ourtaiko_charts.json').read_text())
    if refresh:
        import requests
        from .ese_audio_sync import _ensure_ese_repo
        _ensure_ese_repo()
        response = requests.get('https://taiko.wiki/api/song', timeout=30)
        response.raise_for_status()
        wiki = response.json()
        if not isinstance(wiki,list) or not wiki: raise ValueError('Invalid Wiki snapshot')
        charts = fetch_charts()
    merged, assignments, import_report = merge_catalog(songs, charts)
    mapping = {int(k):v for k,v in json.loads((directory/'song_id2tjapath.json').read_text()).items()}
    resources = enrich_resources(merged, charts, assignments, ese_root, mapping, runtime_root=root, download_missing=refresh)
    # Use current Wiki courses even when the old raw snapshot hid a new Ura.
    from .song_update_task import _apply_levels_and_max_combo, _extract_levels_and_max_combo
    db_by_id = {s['songNo']:s for s in wiki}
    for song in merged:
        from .catalog_chart_policy import is_double_song
        if not is_double_song(song) and str(song['id']) in db_by_id:
            _apply_levels_and_max_combo(song,*_extract_levels_and_max_combo(db_by_id[str(song['id'])]))
    report = reconcile_charts(merged,database=wiki,root=root,ese_root=ese_root,mapping=mapping)
    # Capture all changes against the published catalog, including newly revived courses.
    report['changed'] = catalog_changes(songs, merged)
    atomic_json(directory/'song_id2tjapath.json', {str(k):v for k,v in mapping.items()})
    report['constants'] = fill_constants(merged,output=directory/'catalog_constants.json',csv_path=directory/'constants_id_v2.csv',calculator=calculator,tja_root=ese_root)
    from .song_update_task import _refresh_rating_song_local_metadata
    rating=json.loads((directory/'rating_structured_with_ids.json').read_text())
    report['ratingMetadataRefreshed'] = _refresh_rating_song_local_metadata(rating['songs'],merged)
    report['newRatings'] = {'added':[], 'unavailable':[]}
    if refresh:
        import requests
        from .song_update_task import _fetch_remote_rating_entry, _optional_proxy_dict
        existing = {(row.get('id'),row.get('level')) for row in rating['songs'].values()}
        old = {song['id']:song for song in songs}
        with requests.Session() as session:
            proxies = _optional_proxy_dict()
            if proxies: session.proxies.update(proxies)
            for song in merged:
                if song['id']>=100000 or is_double_song(song): continue
                for level in (4,5):
                    if not isinstance(song.get(f'level_{level}'),int) or (song['id'],level) in existing: continue
                    if isinstance(old.get(song['id'],{}).get(f'level_{level}'),int): continue
                    try:
                        _, key, entry = _fetch_remote_rating_entry(session,song,song['id'],level)
                        if key in rating['songs'] and rating['songs'][key].get('id')!=song['id']:
                            raise ValueError('Rating title collision')
                        rating['songs'][key]=entry
                        report['newRatings']['added'].append([song['id'],level])
                    except Exception as error:
                        report['newRatings']['unavailable'].append({'id':song['id'],'level':level,'reason':str(error)[:160]})
    from sakura_taiko_core.chart.scoreline_dataset import build_scoreline_dataset
    score_rows=json.loads((root/'songs/song_score.json').read_text())
    stream_rows=json.loads((root/'songs/taiko_goku_all_levels_stream.json').read_text())
    unified, matched=build_scoreline_dataset(score_rows,merged,stream_rows)
    report.update(resources=resources,importReport=import_report,scorelineMatched=matched)
    for name,value in [('song_data.json',merged),('taiko_song_database.json',wiki),('ourtaiko_charts.json',charts),
                       ('rating_structured_with_ids.json',rating),('taiko_goku_onis.json',unified)]:atomic_json(directory/name,value)
    atomic_json(stage/'report.json',report)
    return report


def publish(root, stage):
    original=json.loads((stage/'original.json').read_text())
    for name,sha in original.items():
        if digest(root/'songs'/name)!=sha: raise ValueError('Catalog changed during staging: '+name)
    backup=stage/'before';backup.mkdir(exist_ok=False)
    for name in FILES: shutil.copy2(root/'songs'/name,backup/name)
    # Publish metadata last, so consumers never see revived courses with old constants.
    for name in [n for n in FILES if n!='song_data.json']+['song_data.json']:
        path=root/'songs'/name;temporary=path.with_name('.'+name+'.repair')
        shutil.copy2(stage/'songs'/name,temporary);os.replace(temporary,path)
    report=json.loads((stage/'report.json').read_text())
    atomic_json(root/'logs/catalog_chart_sync_report.json', report)
    queue_chart_images(root,report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/home/sigaer/taiko'))
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not os.environ.get('QA_RUN_ID'):parser.error('Run through the memory QA wrapper')
    if args.stage.resolve().is_relative_to(args.root/'songs'):parser.error('Stage outside the live catalog')
    if not (args.stage/'report.json').exists():
        prepare(args.root,args.stage,ese_root=Path('/home/sigaer/git/ESE_autosync'),
                calculator=args.root/'taiko-forum/taiko_viewer/.tja-runtime/calculate.py',refresh=args.refresh)
    if args.apply:publish(args.root,args.stage)
    report=json.loads((args.stage/'report.json').read_text())
    print(json.dumps({'changedSongs':len(report['changed']),'issues':len(report['issues']),'constants':report['constants'],'published':args.apply}))


if __name__=='__main__':main()
