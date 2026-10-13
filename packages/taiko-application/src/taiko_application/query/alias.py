from sakura_taiko_core.chart import identity
from .context import SongQueryContext


def query_aliases(context: SongQueryContext):
    payload = context.aliases
    song_id = context.song_id
    explicit = context.explicit_alias_id
    if not isinstance(payload, list):
        return ("", [], identity._safe_int(song_id, 0))
    target_id = identity._safe_int(song_id, 0)
    if explicit:
        candidate_ids = {target_id}
        display_id = target_id
    else:
        ids = identity.group_ids_for_query(
            song_id=target_id,
            groups_by_id=context.groups_by_id,
            groups_by_title=context.groups_by_title,
        )
        display_id = min(ids) if ids else target_id
        candidate_ids = {display_id}
    for entry in payload:
        if identity._safe_int(entry.get("id"), -1) in candidate_ids:
            return (
                str(entry.get("song_name_jp") or ""),
                list(entry.get("aliases") or []),
                identity._safe_int(entry.get("id"), display_id),
            )
    return ("", [], display_id)
