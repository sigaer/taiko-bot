"""Reconcile old platform/temporary identities with current OurTaiko entries."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
import re
import unicodedata

from taiko_bot.catalog_identity import identity_map


def title_identity(value):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


def _populated(value):
    return value not in (None, "", "-", [], {})


def merge_song_fields(target, previous):
    """Preserve maintained metadata while canonical identity and resources win."""
    inherited = set(target.get("legacy_ids", [])) | set(previous.get("legacy_ids", [])) | {int(previous["id"])}
    target["legacy_ids"] = sorted(inherited - {int(target["id"])})
    wiki = set(target.get("wiki_song_nos", [])) | set(previous.get("wiki_song_nos", []))
    if previous.get("songNo"):
        wiki.add(str(previous["songNo"]))
    if wiki:
        target["wiki_song_nos"] = sorted(wiki)
    # Source IDs and paths belong to the chosen OurTaiko chart, especially when
    # filenames coincide across game/pop categories or old/new audio versions.
    protected = {"id", "sort", "shelf_status", "catalog_source", "ourtaiko_ids", "nijiiro_id",
                 "official_id", "tja_path", "audio_path", "resource_source", "tja_sha256", "audio_sha256", "legacy_ids", "songNo", "wiki_song_nos"}
    for key, value in previous.items():
        if key in protected:
            continue
        current = target.get(key)
        if isinstance(value, list) and isinstance(current, list) and len(value) == len(current) == 5:
            target[key] = [deepcopy(new if _populated(new) else old)
                           for new, old in zip(current, value)]
        elif _populated(value) and not _populated(current):
            target[key] = deepcopy(value)
    if not target.get("official_id") and previous.get("official_id"):
        target["official_id"] = previous["official_id"]


def reconcile_catalog(songs, charts, assignments, *, mapping=None, provenance=None, mainland_ids=None):
    songs = deepcopy(songs)
    by_id = {int(s["id"]): s for s in songs}
    mapping, provenance = mapping or {}, provenance or {}
    canonical = set(assignments.values())
    titles, paths = defaultdict(set), defaultdict(set)
    chart_by_id = {}
    for chart in charts:
        sid = assignments.get(chart["id"])
        if sid is None:
            continue
        chart_by_id[sid] = chart
        for title in [chart.get("title"), *(chart.get("titleTranslations") or {}).values()]:
            if title_identity(title):
                titles[title_identity(title)].add(sid)
        path = by_id[sid].get("tja_path")
        if path:
            paths[path].add(sid)
    known = identity_map(songs, allow_pending=True)
    redirects, unresolved = {}, []
    for previous in songs:
        old = int(previous["id"])
        if old in canonical:
            continue
        target = known.get(old)
        if target not in canonical:
            path = previous.get("tja_path") or mapping.get(str(old)) or mapping.get(old) or provenance.get(str(old), {}).get("tjaPath")
            candidates = {assignments[source] for source in previous.get("ourtaiko_ids", []) if source in assignments}
            if not candidates:
                candidates = paths.get(path, set()) if path else set()
            if not candidates:
                candidates = set().union(*(titles.get(title_identity(previous.get(field)), set()) for field in ("song_name", "song_name_jp")))
                # Without resource identity, require exact course availability
                # and stars. Resource evidence can reconcile outdated wiki stars.
                candidates = {sid for sid in candidates if all(
                    str(previous.get(f"level_{i}", "-")) == str(by_id[sid].get(f"level_{i}", "-"))
                    for i in range(1, 6))}
            target = next(iter(candidates)) if len(candidates) == 1 else None
        if target is None:
            unresolved.append(old)
            continue
        redirects[old] = target
        merge_song_fields(by_id[target], previous)
    active = []
    for song in songs:
        sid = int(song["id"])
        if sid in redirects:
            continue
        chart = chart_by_id.get(sid)
        if not chart and sid < 100000:
            song.setdefault("nijiiro_id", sid)
        if chart:
            rainbow = chart.get("nijiiroId")
            song["nijiiro_id"] = int(rainbow) if rainbow is not None else None
            if rainbow is None:
                song["shelf_status"] = 2
            else:
                ids = {sid, *song.get("legacy_ids", [])}
                song["shelf_status"] = 0 if (ids & mainland_ids if mainland_ids is not None else song.get("shelf_status") == 0) else 1
        if song.get("songNo"):
            song["wiki_song_nos"] = sorted(set(song.get("wiki_song_nos", [])) | {str(song.pop("songNo"))})
        active.append(song)
    identity_map(active)
    return active, {"merged": len(redirects), "redirects": redirects, "unresolvedLocalIds": unresolved}


def load_legacy_provenance(root):
    # Evidence only. The resulting legacy_ids live in the canonical catalog;
    # subsequent daily runs do not depend on the old supplement for identity.
    path = root / "taiko-forum/taiko_viewer/assets/data/v2_console_constants.json"
    return json.loads(path.read_text(encoding="utf-8")).get("provenance", {}) if path.is_file() else {}
