from __future__ import annotations

from taiko_bot.runtime.player.center.hiroba.parser import filter_song_refs_by_levels, merge_song_refs, parse_score_list_page


SCORE_LIST_HTML = """
<li class="contentBox songLisrAreanamco">
  <div class="songNameArea clearfix"><span class="songName songNameFontnamco">Song A</span></div>
  <div class="buttonArea levelSelect">
    <ul class="buttonList">
      <li><a href="score_detail.php?song_no=100&level=4&genre=6"><img class="crown oninamco" src="image/sp/640/crown_button_played_2_640.png"></a></li>
      <li><a href="score_detail.php?song_no=100&level=5&genre=6"><img class="crown oni_uranamco" src="image/sp/640/crown_button_played_3_640.png"></a></li>
    </ul>
  </div>
</li>
"""


def test_parse_score_list_page_keeps_crown_by_level():
    refs = parse_score_list_page(SCORE_LIST_HTML)
    song = refs["100"]
    assert song.levels == {4, 5}
    assert song.crowns == {4: "gold", 5: "dondaful"}


def test_merge_and_filter_song_refs_keep_crowns():
    refs = parse_score_list_page(SCORE_LIST_HTML)
    merged = merge_song_refs([refs])
    filtered = filter_song_refs_by_levels(merged, {5})
    assert filtered["100"].levels == {5}
    assert filtered["100"].crowns == {5: "dondaful"}
