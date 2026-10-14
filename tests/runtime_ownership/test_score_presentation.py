"""Behavior assertions moved from Sakura tests/test_drawinfo.py; installed owner."""
import json
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from taiko_bot.runtime.player.center import presentation
from taiko_application.score import drawinfo as layout
from taiko_application.score.context import ScorePresentationContext

@pytest.fixture
def drawinfo():
    return layout.ScoreInfoRenderer(ScorePresentationContext(Path('.')))

class _MetricTestFont:
    """提供接近 DDFont 的稳定字宽，避免测试依赖未入库字体资源。"""

    def __init__(self, size: int) -> None:
        self.size = size

    def getbbox(self, text: str, *args, **kwargs) -> tuple[int, int, int, int]:
        units = sum(
            1.0
            if ord(char) > 127
            else 0.25
            if char == " "
            else 0.5
            if char == "/"
            else 0.59
            for char in text
        )
        return (0, 0, round(units * self.size), self.size)

def _use_metric_test_font(monkeypatch, drawinfo) -> None:
    monkeypatch.setattr(
        drawinfo,
        "_load_font",
        lambda _font_path, size: _MetricTestFont(size),
    )

def test_prepare_score_presentation_looks_up_song_data_before_collecting_entries(
    tmp_path: Path, monkeypatch
) -> None:
    song_data_path = tmp_path / "song_data.json"
    song_data_path.write_text(
        json.dumps(
            [
                {
                    "id": 1001,
                    "song_name": "Test Song",
                    "song_name_jp": "Test Song JP",
                    "type": "流行音乐",
                    "bpm": 180,
                    "level_1": "-",
                    "level_2": "-",
                    "level_3": "-",
                    "level_4": 8,
                    "level_5": "-",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_collect_entries(data, song_no, *, title="", prefer_best_in_group=False):
        captured["title"] = title
        raise RuntimeError("stop-after-collect")

    monkeypatch.setattr(presentation, "_collect_entries_for_song", fake_collect_entries)

    try:
        presentation.prepare_score_presentation(
            song_no=1001,
            current={"songs": []},
            db_path=str(song_data_path),
        )
    except RuntimeError as exc:
        assert str(exc) == "stop-after-collect"
    else:
        raise AssertionError("prepare_score_presentation should stop in fake collector")

    assert captured["title"] == "Test Song"

def test_v1_double_digit_player_metric_keeps_gap_from_dimension_label(
    monkeypatch, drawinfo,
) -> None:
    _use_metric_test_font(monkeypatch, drawinfo)
    draw = ImageDraw.Draw(Image.new("RGBA", (layout.DETAIL_PANEL_W, 100)))
    label = "复合处理"
    value_parts = ["10.00", " / 10.00"]

    font = drawinfo._fit_detail_metric_font(draw, "unused.ttf", label, value_parts)
    label_width = draw.textbbox((0, 0), label, font=font)[2]
    values_width = sum(draw.textbbox((0, 0), text, font=font)[2] for text in value_parts)
    values_x = layout.DETAIL_PLAYER_VALUE_RIGHT_X - values_width

    assert font.size < layout.DETAIL_METRIC_FONT_SIZE
    assert (
        layout.DETAIL_PLAYER_LABEL_X
        + label_width
        + layout.DETAIL_METRIC_MIN_GAP
        <= values_x
    )

def test_v1_single_digit_player_metric_keeps_original_font_size(monkeypatch, drawinfo) -> None:
    _use_metric_test_font(monkeypatch, drawinfo)
    draw = ImageDraw.Draw(Image.new("RGBA", (layout.DETAIL_PANEL_W, 100)))

    font = drawinfo._fit_detail_metric_font(
        draw,
        "unused.ttf",
        "复合处理",
        ["9.99", " / 9.99"],
    )

    assert font.size == layout.DETAIL_METRIC_FONT_SIZE

def test_v2_constant_labels_use_current_semantics_and_align_with_values(
    monkeypatch, drawinfo,
) -> None:
    _use_metric_test_font(monkeypatch, drawinfo)
    rendered_text: list[tuple[float, int, str, _MetricTestFont]] = []

    def record_text(draw, xy, text, font, fill) -> None:
        rendered_text.append((xy[0], xy[1], text, font))

    monkeypatch.setattr(drawinfo, "_draw_text", record_text)

    drawinfo._draw_detail_panel(
        title="V2 Rating",
        chart_values=None,
        chart_labels=[],
        player_values=None,
        player_labels=[],
        constants=(9.12, 10.34, 11.56),
        font_path="unused.ttf",
        bg_path=None,
        accent=(39, 154, 145),
        constant_labels=("75%", "95%", "99%"),
    )

    by_text = {text: (x, font) for x, _y, text, font in rendered_text}
    assert all(old_label not in by_text for old_label in ("90%", "100%"))
    for center_x, value, label in zip(
        layout.DETAIL_CONSTANT_COLUMN_CENTERS,
        ("9.12", "10.34", "11.56"),
        ("75%", "95%", "99%"),
    ):
        for text in (value, label):
            x, font = by_text[text]
            width = font.getbbox(text)[2]
            assert x + width / 2 == center_x


def test_official_tinfo_mention_uses_unique_runtime_matcher():
    import asyncio
    import nonebot
    from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
    from nonebot.adapters.qq.message import MessageSegment
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    owner = nonebot.require('taiko_bot.runtime.player.entry')
    event = GroupAtMessageCreateEvent(
        id='fixture', content=' tinfo 红 ', timestamp='2026-10-14T00:00:00+00:00',
        author={'id':'fixture-user', 'member_openid':'fixture-user', 'bot':False, 'member_role':'member'},
        group_id='fixture-group', group_openid='fixture-group', to_me=True,
    )
    event.get_message().insert(0, MessageSegment.mention_user('fixture-bot'))
    assert asyncio.run(owner.eligible(event))
    match = owner.PATTERN.match(owner.helpers.extract_plain_text(event).strip())
    assert match and match.group(1) == '红'
    plugin = nonebot.get_plugin('entry')
    assert plugin.matcher == {owner.music_info}
    assert nonebot.require('taiko_bot.runtime.player.entry') is owner
    assert plugin.matcher == {owner.music_info}
    assert len(nonebot.get_plugin('public').matcher) == 9
