from __future__ import annotations

from pathlib import Path

import pytest

from taiko_bot.offline.tja_roll_parser import parse_tja_roll_metadata


TJA_BASIC = """\
BPM:120

COURSE:Oni
LEVEL:8
BALLOON:5,10
#START
5008,
1111,
#END

COURSE:Edit
LEVEL:9
BALLOON:2
#START
00005,
0,
0008,
#END
"""


def test_basic_roll_duration_and_balloons() -> None:
    meta = parse_tja_roll_metadata(TJA_BASIC)

    # Oni：一个连打 5008（BPM120、4/4、4 个音位），5 到 8 相距 3 个音位
    # 每音位 = 240000/120/4 = 500ms，所以 3 音位 = 1.5s
    assert meta["oni"]["roll_times"] == [pytest.approx(1.5)]
    assert meta["oni"]["balloons"] == []

    # Edit：跨小节连打 5(第1小节末) -> 8(第3小节)，中间隔一个空小节(0)
    # BPM120 => 2000ms/measure
    # 第1小节 5 音位：尾段 = 1/5 measure = 400ms
    # 空小节 = 2000ms
    # 第3小节 4 音位：8 在 pos3，头段 = 3/4 measure = 1500ms
    # 总时长 = 400 + 2000 + 1500 = 3900ms = 3.9s
    edit_rt = meta["ura"]["roll_times"]
    assert len(edit_rt) == 1
    assert edit_rt[0] == pytest.approx(3.9)
    assert meta["ura"]["balloons"] == []


def test_duplicate_double_style_prefers_single_chart() -> None:
    text = """\
BPM:120
COURSE:Oni
STYLE:SINGLE
BALLOON:5
#START
5008,
#END
STYLE:DOUBLE
BALLOON:9
#START P1
50000008,
#END
"""

    result = parse_tja_roll_metadata(text)["oni"]

    assert result["roll_times"] == [pytest.approx(1.5)]
    assert result["balloons"] == []


def test_sil_vous_president_ura_finds_missing_long_roll() -> None:
    """用 1061(如果我成为大统领) Ura 验收：taiko.wiki 漏掉的长连打应被识别。

    taiko.wiki 只返回 6 个短连打 0.142×6=0.852s；真实谱面还有一个结尾长连打。
    """
    tja_path = Path(
        "/home/sigaer/git/ESE_autosync/01 Pop/Sil vous President"
    )
    tja_files = list(tja_path.glob("*.tja"))
    if not tja_files:
        pytest.skip("ESE 仓库缺少 1061 的 TJA")
    text = tja_files[0].read_bytes().decode("utf-8-sig")

    meta = parse_tja_roll_metadata(text)

    ura = meta["ura"]
    rt = ura["roll_times"]

    # 6 个短连打：每个 5 音位，BPM176、4/4、48 音位/小节 => 5/48*240000/176 = 142.045ms
    assert len(rt) == 7
    for short in rt[:6]:
        assert short == pytest.approx(0.142045, abs=1e-4)

    # 结尾长连打必须被识别（taiko.wiki 漏掉它）
    assert rt[6] > 1.9
    # 总时长应在 3 秒左右（0.852 + 长连打）
    total = sum(rt)
    assert total == pytest.approx(3.0, abs=0.3)

    # 气球数来自 BALLOON:2
    assert ura["balloons"] == [2]


def test_event_timeline_handles_bpmchange_and_split_measure() -> None:
    text = """\
BPM:120
COURSE:Oni
#START
5
00,
#BPMCHANGE 240
0
08,
#END
"""
    # First measure has eight slots at 120 BPM: 5 -> 8 is 7 * 250 ms.
    # The second measure has four slots at 240 BPM: 5 -> 8 is 3 * 250 ms.
    assert parse_tja_roll_metadata(text)["oni"]["roll_times"] == [2.666667]


def test_event_timeline_applies_measure_and_delay() -> None:
    text = """\
BPM:120
COURSE:Oni
#START
#MEASURE 2/4
5008,
#DELAY 1.25
5008,
#END
"""
    # 2/4 makes the first 4-note measure last one second; delay is in seconds.
    assert parse_tja_roll_metadata(text)["oni"]["roll_times"] == [0.75, 0.75]


def test_event_timeline_keeps_branch_variants_separate() -> None:
    text = """\
BPM:120
COURSE:Oni
BALLOON:7
#START
#BRANCHSTART p,50,80
#N
5008,
#E
50008,
#M
500008,
#BRANCHEND
#END
"""
    result = parse_tja_roll_metadata(text)["oni"]
    assert result["balloons"] == []
    assert {key: value["roll_times"] for key, value in result["branches"].items()} == {
        "N": [1.5],
        "E": [1.6],
        "M": [1.666667],
    }
    assert result["roll_times"] == [1.666667]
