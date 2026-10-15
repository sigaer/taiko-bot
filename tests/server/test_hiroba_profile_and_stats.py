from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from taiko_bot.runtime.player.center.draw_dress import draw_player_info
from taiko_bot.runtime.player.center.hiroba.parser import (
    parse_mypage_achievement,
    parse_profile,
    parse_score_detail,
)


MYPAGE_HTML = """
<div id="mydon_area" class="mydon_area">
  <img src="imgsrc_titleplate.php">
  <div>フルコンボなんて夢のまた夢</div>
  <div>
    <div>空の神秘</div>
    <div><img src="imgsrc_danlabel.php?taiko_no=519635636897"></div>
  </div>
  <div>
    <div class="detail">
      <p>都道府県 ：東京都</p>
      <p>太鼓番：519635636897</p>
    </div>
  </div>
  <div class="total_score">
    <img src="image/sp/640/total_score_image_5.png">
    <div class="best_rank_score_8">903</div>
    <div class="best_rank_score_7">516</div>
    <div class="best_rank_score_6">21</div>
    <div class="best_rank_score_5">14</div>
    <div class="best_rank_score_4">0</div>
    <div class="best_rank_score_3">0</div>
    <div class="best_rank_score_2">0</div>
    <div class="silver_crown_count">49</div>
    <div class="gold_crown_count">593</div>
    <div class="donderful_crown_count">812</div>
  </div>
</div>
"""


PUBLIC_PROFILE_HTML = """
<div id="mydon_area" class="mydon_area">
  <img src="imgsrc_titleplate.php?taiko_no=519635636897">
  <div>2024赤銀超人★2025赤銀超人</div>
  <div>
    <div>空の神秘</div>
  </div>
  <div>
    <div class="detail">
      <p>国・地域 ：未設定</p>
      <p>太鼓番：519635636897</p>
    </div>
  </div>
  <div class="total_score">
    <img src="image/sp/640/total_score_image_5.png">
    <div class="best_rank_score_8">910</div>
    <div class="best_rank_score_7">502</div>
    <div class="best_rank_score_6">21</div>
    <div class="best_rank_score_5">15</div>
    <div class="best_rank_score_4">0</div>
    <div class="best_rank_score_3">0</div>
    <div class="best_rank_score_2">0</div>
    <div class="silver_crown_coun">50</div>
    <div class="gold_crown_count">580</div>
    <div class="donderful_crown_count">818</div>
  </div>
</div>
"""


SCORE_DETAIL_HTML = """
<div id="content"></div>
<div class="scoreDetailStatus">
  <img class="crown" src="image/sp/640/crown_large_3_640.png" />
  <img class="best_score_icon" src="image/sp/640/best_score_rank_8_640.png" />
</div>
<div class="high_score"><span>1002820点</span></div>
<div class="ranking"><span>12位</span></div>
<div class="good_cnt"><span>406回</span></div>
<div class="ok_cnt"><span>0回</span></div>
<div class="ng_cnt"><span>0回</span></div>
<div class="combo_cnt"><span>406回</span></div>
<div class="pound_cnt"><span>0打</span></div>
<div class="stage_cnt"><span>3回</span></div>
<div class="clear_cnt"><span>3回</span></div>
<div class="full_combo_cnt"><span>2回</span></div>
<div class="dondaful_combo_cnt"><span>1回</span></div>
"""


def test_parse_profile_and_mypage_achievement():
    profile = parse_profile(MYPAGE_HTML)
    assert profile.nickname == "空の神秘"
    assert profile.title == "フルコンボなんて夢のまた夢"
    assert profile.taiko_no == "519635636897"

    achievement = parse_mypage_achievement(MYPAGE_HTML)
    assert achievement == {
        "count_level": 5,
        "ary_crown_count": [49, 593, 812],
        "ary_score_rank_count": [0, 0, 0, 14, 21, 516, 903],
    }


def test_parse_public_profile_and_stats():
    profile = parse_profile(PUBLIC_PROFILE_HTML)
    assert profile.nickname == "空の神秘"
    assert profile.title == "2024赤銀超人★2025赤銀超人"
    assert profile.taiko_no == "519635636897"
    assert profile.region == "未設定"

    achievement = parse_mypage_achievement(PUBLIC_PROFILE_HTML)
    assert achievement == {
        "count_level": 5,
        "ary_crown_count": [50, 580, 818],
        "ary_score_rank_count": [0, 0, 0, 15, 21, 502, 910],
    }


def test_parse_score_detail_reads_dondaful_combo_count():
    detail = parse_score_detail(SCORE_DETAIL_HTML, "2", 4)
    assert detail is not None
    assert detail.crown == "dondaful"
    assert detail.badge == "rainbow"
    assert detail.full_combo_cnt == 2
    assert detail.dondaful_combo_cnt == 1


def test_draw_player_info_places_name_above_title(monkeypatch):
    recorded_texts: list[str] = []

    def fake_draw_text_center(*_args, **kwargs):
        recorded_texts.append(str(_args[2]))

    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.draw_dress._draw_text_center",
        fake_draw_text_center,
    )

    userdata = {
        "profile": {
            "gameCostume": {
                "mydon_name": "NAME",
                "title": "TITLE",
            }
        }
    }
    base = Image.new("RGBA", (499, 1600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    font = ImageFont.load_default()

    draw_player_info(
        base,
        draw,
        userdata,
        1.0,
        1.0,
        font,
        1,
        (255, 255, 255),
        (0, 0, 0),
    )

    assert recorded_texts[:2] == ["TITLE", "NAME"]
