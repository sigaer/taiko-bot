"""Small synthetic public-style catalog and outcomes; no player data or external IO."""

from types import SimpleNamespace

SONGS = [
    {
        "id": 1,
        "song_name": "霓虹",
        "song_name_jp": "Neon",
        "shelf_status": 0,
        "sort": 2,
        "level_4": "9",
        "level_5": "10",
        "type": "流行音乐",
    },
    {
        "id": 2,
        "song_name": "霓虹",
        "song_name_jp": "Neon",
        "shelf_status": 1,
        "sort": 3,
        "level_4": "9",
        "level_5": "10",
        "type": "流行音乐",
    },
    {
        "id": 3,
        "song_name": "月光",
        "song_name_jp": "Moon",
        "shelf_status": 0,
        "sort": 1,
        "level_4": "8",
        "level_5": "-",
        "type": "游戏音乐",
    },
    {"id": 4, "song_name": "", "song_name_jp": "", "shelf_status": 0, "level_4": "7"},
] + [
    {
        "id": i,
        "song_name": f"曲目{i}",
        "song_name_jp": f"Track {i}",
        "shelf_status": 0,
        "sort": i,
        "level_4": "9",
        "level_5": "-",
    }
    for i in range(10, 42)
]
ALIASES = [
    {"id": 1, "song_name_jp": "Neon", "aliases": ["灯光", "NE", "common", None, 99]},
    {"id": 2, "song_name_jp": "Neon", "aliases": ["霓虹旧版", "common"]},
    {"id": 3, "song_name_jp": "Moon", "aliases": ["月亮", "common"]},
    {"id": "bad-id", "song_name_jp": "Unknown", "aliases": ["ghost"]},
]
CHARTS = [
    {
        "id": s["id"],
        "level": 4,
        "score": 6.6,
        "combo": 500,
        "bpm": "140",
        "平均密度": 6.125,
        "体力": 10.4,
        "节奏处理": 9,
        "复合处理": 7.8,
        "平均": 9.1,
    }
    for s in SONGS
]
CHARTS += [
    dict(CHARTS[0]),
    {"id": "broken", "level": "?", "score": 6.6},
    {"id": 1, "level": 5, "score": 9.3, "combo": 600},
]
STATIC = {
    "9.0": [1, 1, 2, 3, 100001, "ignored"],
    "10.0": [100001],
    "garbage": [1],
    "8.5": [],
}
BEST = {
    (1, 4): {"clear_cnt": 1, "best_score_rank": 3},
    (1, 5): {"dondaful_combo_cnt": 1, "best_score_rank": 8},
    (3, 4): {"full_combo_cnt": 1, "best_score_rank": 5},
}
RECOMMENDATIONS = [
    {
        "song_id": 1,
        "level": 4,
        "title": "Neon",
        "is_unplayed": False,
        "song_indicator": 12.34567891,
        "reference_indicator": 11,
        "indicator_deviation_percent": 0.1222333444,
        "is_in_strict_range": True,
    },
    {"song_id": 1, "level": 4, "title": "Neon duplicate", "is_unplayed": True},
    {"song_id": 0, "level": 4},
    {"song_id": 3, "level": 4, "title": None, "song_indicator": None},
]
TARGET = SimpleNamespace(
    target_key="full_combo",
    candidate_count=3,
    required_count=2,
    is_enough=True,
    rows=[
        {
            "song_id": 1,
            "level": 4,
            "star": "9",
            "title": "Neon",
            "score": 990000,
            "target_score": 1000000,
            "gap_kind": "score",
            "gap_value": 10000,
            "progress": 98.12345,
            "recommend_index": 82.129,
        },
        {
            "song_id": 3,
            "level": 4,
            "score": None,
            "target_score": None,
            "gap_value": None,
            "is_unplayed": True,
        },
        {"song_id": 0, "level": 0},
    ],
)
