"""Real synthetic TJA parsing/publication and daily-task integration."""
import json
from pathlib import Path

import pytest

from taiko_bot.offline import merge_index, song_update_task


def tja(root, name, *, title=None, bpm=180, notes='1212120000000000'):
    path = root / (name + '.tja')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'TITLE:{title or name}\nBPM:{bpm}\nCOURSE:Oni\nLEVEL:9\n#START\n{notes},\n#END\n',
        encoding='utf-8',
    )
    return path


def song(number=7, name='Synthetic'):
    return {'id': number, 'song_name': name, 'song_name_jp': name,
            'shelf_status': 0, 'level_4': 9}


def rebuild(root, songs, **kwargs):
    return merge_index.rebuild_pattern_index(
        songs, tja_root=root / 'tja', output_path=root / 'index.json',
        report_path=root / 'report.json', **kwargs,
    )


def read(root):
    return json.loads((root / 'index.json').read_text())


def test_new_and_modified_tja_refresh_actual_bpm_and_pattern_index(tmp_path):
    tja(tmp_path / 'tja', 'Synthetic')
    report = rebuild(tmp_path, [song()])
    assert report['matched_song_count'] == 1
    before = read(tmp_path)
    assert before['by_tag']['16 oxoxox'] == ['Synthetic||Oni']
    tja(tmp_path / 'tja', 'Synthetic', bpm=200, notes='2221110000000000')
    tja(tmp_path / 'tja', 'Added', bpm=240)
    report = rebuild(tmp_path, [song(), song(8, 'Added'), {**song(9, 'Removed'), 'shelf_status': 1}])
    after = read(tmp_path)
    assert report['matched_song_count'] == 2
    assert after['by_bpm']['200'] == ['Synthetic||Oni']
    assert after['by_tag']['16 xxxooo'] == ['Synthetic||Oni']
    assert after['by_tag']['16 oxoxox'] == ['Added||Oni']
    assert set(after['song_meta']) == {'Synthetic', 'Added'}
    assert json.loads((tmp_path / 'index.json.previous').read_text()) == before


def test_strict_failure_keeps_previous_generation(tmp_path):
    tja(tmp_path / 'tja', 'Synthetic')
    rebuild(tmp_path, [song()])
    before = (tmp_path / 'index.json').read_bytes()
    with pytest.raises(ValueError, match='not published'):
        rebuild(tmp_path, [song(), song(8, 'Missing')])
    assert (tmp_path / 'index.json').read_bytes() == before
    assert not (tmp_path / 'index.json.previous').exists()
    assert json.loads((tmp_path / 'report.json').read_text())['skipped_song_ids'] == [8]


def test_daily_partial_progress_retains_failed_song_and_skips_missing_new_tja(tmp_path):
    tja(tmp_path / 'tja', 'Synthetic')
    rebuild(tmp_path, [song()])
    tja(tmp_path / 'tja', 'Added', bpm=240)
    report = rebuild(tmp_path, [song(), song(8, 'Added'), song(9, 'Missing')],
                     song_tja_mapping={7: 'missing.tja', 8: 'Added.tja'}, allow_partial=True)
    result = read(tmp_path)
    assert report['retained_song_ids'] == [7]
    assert report['skipped_song_ids'] == [9]
    assert report['matched_song_count'] == 1
    assert result['by_bpm']['180'] == ['Synthetic||Oni']
    assert result['by_bpm']['240'] == ['Added||Oni']
    assert {s['id'] for s in result['song_meta'].values()} == {7, 8}


def test_existing_mapping_selects_real_version_without_fuzzy_fallback(tmp_path):
    tja(tmp_path / 'tja', 'old', title='Synthetic', bpm=180)
    tja(tmp_path / 'tja', 'new', title='Synthetic', bpm=200)
    rebuild(tmp_path, [song()], song_tja_mapping={7: 'new.tja'})
    assert set(read(tmp_path)['by_bpm']) == {'200'}
    before = (tmp_path / 'index.json').read_bytes()
    with pytest.raises(ValueError, match='not published'):
        rebuild(tmp_path, [song()], song_tja_mapping={7: ''}, allow_partial=True)
    assert (tmp_path / 'index.json').read_bytes() == before


def test_retained_duplicate_title_rekeys_all_index_references(tmp_path):
    tja(tmp_path / 'tja', 'Synthetic')
    rebuild(tmp_path, [song()])
    tja(tmp_path / 'tja', 'new', title='Synthetic', bpm=240)
    report = rebuild(tmp_path, [song(), song(8)],
                     song_tja_mapping={7: '', 8: 'new.tja'}, allow_partial=True)
    result = read(tmp_path)
    assert report['retained_song_ids'] == [7]
    assert result['by_bpm']['180'] == ['Synthetic@@7||Oni']
    assert result['by_bpm']['240'] == ['Synthetic@@8||Oni']
    assert result['by_tag']['16 oxoxox'] == ['Synthetic@@7||Oni', 'Synthetic@@8||Oni']
    assert set(result['song_meta']) == {'Synthetic@@7', 'Synthetic@@8'}


def test_failed_atomic_replace_keeps_usable_current_and_backup(tmp_path, monkeypatch):
    tja(tmp_path / 'tja', 'Synthetic')
    rebuild(tmp_path, [song()])
    before = read(tmp_path)
    original = merge_index.os.replace

    def replace(source, target):
        if Path(target) == tmp_path / 'index.json':
            raise OSError('synthetic disk publication failure')
        return original(source, target)

    monkeypatch.setattr(merge_index.os, 'replace', replace)
    with pytest.raises(OSError, match='publication failure'):
        rebuild(tmp_path, [song()])
    assert read(tmp_path) == before
    assert json.loads((tmp_path / 'index.json.previous').read_text()) == before
    assert not list(tmp_path.glob('.*.tmp'))


@pytest.mark.parametrize('failure', ['empty', 'invalid-previous', 'missing-root'])
def test_invalid_inputs_never_replace_current_index(tmp_path, failure):
    tja(tmp_path / 'tja', 'Synthetic')
    rebuild(tmp_path, [song()])
    if failure == 'invalid-previous':
        (tmp_path / 'index.json').write_text('{"song_meta":{}}')
    if failure == 'missing-root':
        (tmp_path / 'tja').rename(tmp_path / 'absent')
    before = (tmp_path / 'index.json').read_bytes()
    with pytest.raises((ValueError, FileNotFoundError)):
        rebuild(tmp_path, [] if failure == 'empty' else [song()])
    assert (tmp_path / 'index.json').read_bytes() == before


def test_daily_hook_parses_new_tja_only_after_repository_sync(tmp_path, monkeypatch):
    mirror = tmp_path / 'tja'
    monkeypatch.setattr(song_update_task, 'ROOT_DIR', tmp_path)
    monkeypatch.setattr(song_update_task, 'ESE_SYNC_REPO_PATH', mirror)

    def sync(songs, **kwargs):
        tja(mirror, 'new', title='Synthetic', bpm=240)
        return {'success': False, 'repo': {'repo_path': str(mirror), 'revision': 'synthetic-revision'}}

    monkeypatch.setattr(song_update_task, 'sync_audio_from_ese', sync)
    report = song_update_task._sync_audio_and_chart_config([song()], {7: 'new.tja'})
    assert report['success'] is False  # Audio conversion does not block successfully synchronized TJA.
    index = json.loads((tmp_path / 'songs/analyze_result_filtered.json').read_text())
    assert index['by_bpm']['240'] == ['Synthetic||Oni']


@pytest.mark.parametrize('repo', [{}, {'revision': 'synthetic', 'repo_path': '/not-the-managed-mirror'}])
def test_daily_hook_preserves_index_when_repository_sync_fails(tmp_path, monkeypatch, repo):
    monkeypatch.setattr(song_update_task, 'ROOT_DIR', tmp_path)
    monkeypatch.setattr(song_update_task, 'ESE_SYNC_REPO_PATH', tmp_path / 'tja')
    target = tmp_path / 'songs/analyze_result_filtered.json'
    target.parent.mkdir();target.write_text('previous-index')
    monkeypatch.setattr(song_update_task, 'sync_audio_from_ese', lambda *a, **k: {'repo': repo})
    song_update_task._sync_audio_and_chart_config([song()], {})
    assert target.read_text() == 'previous-index'


def test_daily_hook_reports_parser_failure_without_failing_other_updates(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(song_update_task, 'ROOT_DIR', tmp_path)
    mirror = tmp_path / 'tja';mirror.mkdir()
    monkeypatch.setattr(song_update_task, 'ESE_SYNC_REPO_PATH', mirror)
    audio_report = {'repo': {'repo_path': str(mirror), 'revision': 'synthetic'}}
    monkeypatch.setattr(song_update_task, 'sync_audio_from_ese', lambda *a, **k: audio_report)
    def failed(*args, **kwargs):
        raise OSError('synthetic parser failure')
    monkeypatch.setattr(merge_index, 'rebuild_pattern_index', failed)
    assert song_update_task._sync_audio_and_chart_config([song()], {}) is audio_report
    assert '配置索引更新失败' in caplog.text


def test_overlapping_rebuild_is_rejected_without_overwriting_index(tmp_path):
    tja(tmp_path / 'tja', 'Synthetic')
    rebuild(tmp_path, [song()])
    before = (tmp_path / 'index.json').read_bytes()
    with (tmp_path / 'index.json.lock').open('a') as lock:
        merge_index.fcntl.flock(lock, merge_index.fcntl.LOCK_EX | merge_index.fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            rebuild(tmp_path, [song()])
    assert (tmp_path / 'index.json').read_bytes() == before


def test_parser_exception_does_not_publish_partial_file(tmp_path, monkeypatch):
    tja(tmp_path / 'tja', 'Synthetic')
    rebuild(tmp_path, [song()])
    before = (tmp_path / 'index.json').read_bytes()
    def failed(*args, **kwargs):
        raise ValueError('synthetic parser error')
    monkeypatch.setattr(merge_index, 'build_song_records', failed)
    with pytest.raises(ValueError, match='synthetic parser error'):
        rebuild(tmp_path, [song()], allow_partial=True)
    assert (tmp_path / 'index.json').read_bytes() == before
