from __future__ import annotations


V2_DIM_COLUMNS = ["体力", "手速", "爆发", "精度", "节奏", "复合"]

V2_TAIKOB_DIM_ALIASES = {
    "体力": "体力",
    "stamina": "体力",
    "手速": "手速",
    "高速": "手速",
    "高速处理": "手速",
    "handspeed": "手速",
    "speed": "手速",
    "爆发": "爆发",
    "爆发力": "爆发",
    "burst": "爆发",
    "精度": "精度",
    "精度力": "精度",
    "accuracy": "精度",
    "accuracy_power": "精度",
    "节奏": "节奏",
    "节奏处理": "节奏",
    "rhythm": "节奏",
    "复合": "复合",
    "复合处理": "复合",
    "complex": "复合",
}

V2_TREND_DIM_ALIASES = {
    **V2_TAIKOB_DIM_ALIASES,
    "rating": "综合Rating",
    "综合": "综合Rating",
    "总合": "综合Rating",
    "综合rating": "综合Rating",
    "ra": "综合Rating",
}

V2_TREND_SHORT_LABELS = {
    "体力": "体力",
    "手速": "手速",
    "爆发": "爆发",
    "精度": "精度",
    "节奏": "节奏",
    "复合": "复合",
    "综合Rating": "综合",
}

V2_TREND_COLORS = {
    "体力": "#F28E2B",
    "手速": "#E15759",
    "爆发": "#B07AA1",
    "精度": "#76B7B2",
    "节奏": "#59A14F",
    "复合": "#4E79A7",
    "综合Rating": "#111111",
}
