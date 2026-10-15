from __future__ import annotations

from taiko_bot.runtime.player.center.hiroba.client import (
    HirobaError,
    _choose_hiroba_card,
    _parse_login_select_cards,
)
from taiko_bot.runtime.player.center.hiroba.sync import sync_multiple_hiroba_userdatas


LOGIN_SELECT_HTML = """
<ul>
  <li class="contentBox cardSelect">
    <div id="mydon_area">
      <div><p class="no">太鼓番: 111111111111</p></div>
      <div>Alpha</div>
    </div>
    <div>アクセスコード：1111-2222-3333-4444-5555</div>
    <form action="login_select.php">
      <input type="hidden" name="id_pos" value="1">
      <input type="hidden" name="mode" value="exec">
    </form>
  </li>
  <li class="contentBox cardSelect">
    <div id="mydon_area">
      <div><p class="no">太鼓番: 222222222222</p></div>
      <div>Beta</div>
    </div>
    <div>アクセスコード：9999-8888-7777-6666-5555</div>
    <form action="login_select.php">
      <input type="hidden" name="id_pos" value="2">
      <input type="hidden" name="mode" value="exec">
    </form>
  </li>
  <li class="contentBox cardSelect">
    <div>アクセスコード：0000-0000-0000-0000-0000</div>
    <div>※太鼓の達人でのプレイ履歴がないため、データの閲覧ができません。</div>
  </li>
</ul>
"""


MALFORMED_LOGIN_SELECT_HTML = """
<ul>
  <li class="contentBox cardSelect">
    <div id="mydon_area">
      <div><p class="no">太鼓番: 519635636897</p></div>
      <div>Alpha</div>
    </div>
    <form action="login_select.php">
      <input type="hidden" name="id_pos" value="1">
      <input type="hidden" name="mode" value="exec">
    </form>
  <li>
  <li class="contentBox cardSelect">
    <div>※太鼓の達人でのプレイ履歴がないため、データの閲覧ができません。</div>
  </li>
</ul>
"""


def test_parse_login_select_cards():
    cards = _parse_login_select_cards(LOGIN_SELECT_HTML)
    assert len(cards) == 3
    assert cards[0].id_pos == 1
    assert cards[0].taiko_no == "111111111111"
    assert cards[0].display_name == "Alpha"
    assert cards[0].has_play_data is True
    assert cards[2].has_play_data is False


def test_parse_login_select_cards_ignores_nested_no_play_warning():
    cards = _parse_login_select_cards(MALFORMED_LOGIN_SELECT_HTML)
    assert len(cards) == 2
    assert cards[0].taiko_no == "519635636897"
    assert cards[0].has_play_data is True
    assert cards[1].has_play_data is False


def test_choose_hiroba_card_prefers_explicit_taiko_no():
    cards = _parse_login_select_cards(LOGIN_SELECT_HTML)
    selected = _choose_hiroba_card(cards, taiko_no="222222222222")
    assert selected.id_pos == 2
    assert selected.display_name == "Beta"


def test_choose_hiroba_card_without_target_raises_on_multiple_playable_cards():
    cards = _parse_login_select_cards(LOGIN_SELECT_HTML)
    try:
        _choose_hiroba_card(cards)
    except HirobaError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected HirobaError")

    assert "多个可同步的太鼓番" in message
    assert "111111111111(Alpha)" in message
    assert "222222222222(Beta)" in message


def test_sync_multiple_hiroba_userdatas_respects_target(monkeypatch):
    discovered = _parse_login_select_cards(LOGIN_SELECT_HTML)[:2]
    synced: list[str] = []

    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.discover_hiroba_playable_cards",
        lambda *_args, **_kwargs: discovered,
    )

    def fake_sync_hiroba_userdata(*_args, **kwargs):
        synced.append(str(kwargs["taiko_no"]))
        return str(kwargs["taiko_no"])

    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.sync_hiroba_userdata",
        fake_sync_hiroba_userdata,
    )

    result = sync_multiple_hiroba_userdatas(
        "test@example.com",
        "secret",
        target_taiko_no="222222222222",
    )

    assert result == ["222222222222"]
    assert synced == ["222222222222"]
