from __future__ import annotations
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple, Iterable, Literal, Sequence
from ..models.calculation import SongMetrics, RatingResult, SongStats, V2SongData, V2RatingResult, FullScoreRef
def _build_song_index_by_id_level(songs: dict) -> Dict[tuple, tuple]:
    """
    (id, level) -> (song_key_in_cfg, song_info)
    注意：song_key_in_cfg 是 songs 字典的 key，不一定等于 song_name_cn
    """
    idx = {}
    for k in songs:
        info = songs[k]
        try:
            sid = int(info.get("id"))
            lvl = int(info.get("level"))
        except Exception:
            continue
        idx[(sid, lvl)] = (k, info)
    return idx

def _get_recommend_identity_key(song_id: int, level: int, default_ids: Mapping[int, int] | None = None, *, identity_namespace: str = 'title') -> Tuple[str, int, int]:
    """
    推荐流程的歌曲身份键：
    - 同名多版本歌曲：按默认版本 id + level 视为同一项
    - 其余歌曲：按 song_id + level 区分
    """
    if identity_namespace not in {'title', 'pair'}:
        raise ValueError('unknown identity namespace')
    return (identity_namespace, default_ids[song_id], level) if default_ids and song_id in default_ids else ("song", song_id, level)

def _build_song_index_by_identity(songs: dict, default_ids: Mapping[int, int] | None = None, visible_song_ids: set[int] | None = None, *, identity_namespace: str = 'title') -> Dict[tuple, tuple]:
    """
    (identity_key) -> (song_key_in_cfg, song_info)
    用于推荐流程按歌曲身份匹配，避免同标题歌曲互相串歌。
    """
    idx = {}
    for k in songs:
        info = songs[k]
        try:
            sid = int(info.get("id"))
            lvl = int(info.get("level"))
        except Exception:
            continue
        if visible_song_ids is not None and sid not in visible_song_ids:
            continue
        idx.setdefault(_get_recommend_identity_key(sid, lvl, default_ids, identity_namespace=identity_namespace), (k, info))
    return idx

def _find_song_info_for_recommend_record(
    song_id: int,
    level: int,
    idx_by_id_level: Dict[tuple, tuple],
    idx_by_identity: Dict[tuple, tuple],
    default_ids: Mapping[int, int] | None = None,
    *, identity_namespace: str = 'title',
) -> Optional[tuple]:
    """
    优先按原始 song_id + level 精确匹配；
    如果结构化曲库没有该 ID，则回退到“同曲组 + 同难度”的谱面信息。
    这样可以用同谱面版本完成计算，同时保留用户实际游玩的 song_id。
    """
    exact = idx_by_id_level.get((song_id, level))
    if exact is not None:
        return exact
    return idx_by_identity.get(_get_recommend_identity_key(song_id, level, default_ids, identity_namespace=identity_namespace))

def _get_title_like_existing(song_info: dict, level: int) -> str:
    """
    完全复用你 compute_all_from_userdata 内的命名方式：
    title = song_info["song_name_cn"] + "(里谱)" if level==5
    这样 title 才能和你 RatingResult.song_name 保持一致，也能用于推荐。
    """
    title = song_info.get("song_name_cn") or song_info.get("曲名") or ""
    if level == 5:
        title += "(里谱)"
    return title
