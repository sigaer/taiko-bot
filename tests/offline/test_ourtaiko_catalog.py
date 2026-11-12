from copy import deepcopy

import pytest

from taiko_bot.offline.ourtaiko_catalog import fetch_charts, fetch_paginated_charts, merge_catalog
from taiko_bot.offline.catalog_resources import enrich_resources, safe_resource


def chart(key, rainbow=None, title="New", **fields):
    return {"id": key, "numberId": 1, "nijiiroId": rainbow, "title": title,
            "difficulties": [{"course": "Oni", "side": "single", "level": 8}], **fields}


def test_incremental_identity_preserves_existing_fields_and_ids():
    old = [{"id": 7, "song_name": "Local", "shelf_status": 0, "level_4": 9, "max_combo": [0,0,0,700,0], "official_id": "local"},
           {"id": 100004, "song_name": "Console", "shelf_status": 2, "level_4": 8}]
    frozen = deepcopy(old)
    charts = [chart("a", 7, officialId="remote"), chart("b", 8), chart("c", title="Console"), chart("d", title="Other")]
    songs, assignments, report = merge_catalog(old, charts, mainland_ids={7})
    assert old == frozen
    by_id = {s["id"]: s for s in songs}
    for song in old:
        assert all(by_id[song["id"]][key] == value for key, value in song.items())
    assert assignments == {"a": 7, "b": 8, "c": 100004, "d": 100005}
    assert by_id[8]["shelf_status"] == 1
    assert by_id[100005]["shelf_status"] == 2
    again, second, _ = merge_catalog(songs, charts, mainland_ids=set())
    assert len(again) == len(songs)
    assert second == assignments
    assert next(s for s in again if s["id"] == 7)["shelf_status"] == 0
    assert report["issues"][0]["reason"] == "official_id_conflict"


def test_no_title_match_can_steal_a_nijiiro_identity():
    songs, assignments, _ = merge_catalog([{ "id": 9, "song_name": "New", "shelf_status": 0}], [chart("a"), chart("b", 10)])
    assert assignments == {"a": 100000, "b": 10}
    assert len(songs) == 3


def test_pagination_rejects_partial_and_duplicate_pages(monkeypatch):
    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value
    pages = {1: {"page": 1, "pageSize": 1, "total": 2, "items": [{"id": "a"}]},
             2: {"page": 2, "pageSize": 1, "total": 2, "items": [{"id": "b"}]}}
    monkeypatch.setattr("taiko_bot.offline.ourtaiko_catalog.requests.get", lambda *a, params, **kw: Response(pages[params["page"]]))
    assert len(fetch_paginated_charts()) == 2
    pages[2]["items"] = [{"id": "a"}]
    with pytest.raises(ValueError, match="duplicate"):
        fetch_paginated_charts()
    pages[2]["items"] = []
    with pytest.raises(ValueError, match="Incomplete"):
        fetch_paginated_charts()


def test_full_catalog_unions_fileless_and_checks_complete_coverage(monkeypatch):
    calls = []
    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value
    def get(url, params=None, **kwargs):
        calls.append((url, params))
        if url.endswith('/game/catalog'):
            return Response({'charts': [chart('a', 1)], 'chartCount': 1})
        return Response({'page': 1, 'pageSize': 24, 'total': 1 if params.get('files') else 2,
                         'items': [chart('b', 2)] if params.get('files') else [chart('a', 1),chart('b', 2)]})
    monkeypatch.setattr('taiko_bot.offline.ourtaiko_catalog.requests.get', get)
    assert [c['id'] for c in fetch_charts()] == ['a', 'b']
    assert len(calls) == 3


def test_full_catalog_falls_back_when_uncategorized_song_is_missing(monkeypatch):
    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value
    def get(url, params=None, **kwargs):
        if url.endswith('/game/catalog'):
            return Response({'charts': [chart('a', 1)], 'chartCount': 1})
        rows = [] if params.get('files') else [chart('a',1),chart('b',2)]
        return Response({'page':1,'pageSize':24,'total':len(rows),'items':rows})
    monkeypatch.setattr('taiko_bot.offline.ourtaiko_catalog.requests.get', get)
    assert [c['id'] for c in fetch_charts()] == ['a','b']


def test_resource_gaps_do_not_block_other_songs_or_escape_root(tmp_path):
    (tmp_path / "match.tja").write_text("TITLE:New\nBPM:120\nWAVE:match.ogg\nCOURSE:Oni\nLEVEL:8\n#START\n1111,\n#END\n")
    (tmp_path / "match.ogg").write_bytes(b"test")
    songs = [{"id": 100000}, {"id": 100001}]
    charts = [chart("a", tjaName="match.tja"), chart("b", tjaName="missing.tja")]
    mapping = {}
    report = enrich_resources(songs, charts, {"a":100000, "b":100001}, tmp_path, mapping)
    assert report["matched"] == 1 and report["missing"] == 1
    assert songs[0]["audio_path"] == "match.ogg"
    assert songs[1]["tja_path"] == ""
    assert mapping == {"100000": "match.tja"}
    assert safe_resource(tmp_path, "../outside.tja") is None


def test_constants_only_append_missing_rows_and_validate_chart_identity(tmp_path):
    import csv
    import json
    from taiko_bot.offline.catalog_constants import FIELDS, fill_constants
    model = tmp_path / "Constants"
    model.mkdir()
    (model / "cached_computing_parameters.json").write_text("{}")
    values = {key: 6.0 for key in FIELDS[4:]}
    calculator = tmp_path / "calculate.py"
    calculator.write_text("def calculate(data, node):\n    return " + repr({"charts": [{"course": "oni", "branch": "unbranched", "totalNotes": 100, "constants": values}]}))
    (tmp_path / "chart.tja").write_text("COURSE:Oni\nLEVEL:8\n#START\n1111,\n#END\n")
    dataset = tmp_path / "constants.csv"
    original = {"id": "1", "title": "Existing", "difficulty": "oni", "totalNotes": "100", **{key: "9" for key in FIELDS[4:]}}
    with dataset.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerow(original)
    songs = [{"id": sid, "song_name": "Test", "level_4": 8, "tja_path": "chart.tja", "catalog_source": "ourtaiko", "max_combo": ["-"]*5} for sid in [1,2,3]]
    songs[2]["max_combo"][3] = 101
    report = fill_constants(songs, output=tmp_path / "supplement.json", csv_path=dataset, calculator=calculator, tja_root=tmp_path)
    rows = list(csv.DictReader(dataset.open()))
    assert rows[0] == original and len(rows) == 2
    assert rows[1]["id"] == "2"
    assert report["addedCharts"] == 1
    assert songs[1]["max_combo"][3] == 100 and songs[2]["max_combo"][3] == 101
    payload = json.loads((tmp_path / "supplement.json").read_text())
    assert payload["issues"][0]["reason"] == "note_count_mismatch"
