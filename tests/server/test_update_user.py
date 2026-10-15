from taiko_bot.runtime.player.center import update_user


def test_select_search_player_prefers_exact_userid():
    first = {"userid": "7425375", "gameCostume": {"title": "old"}}
    exact = {"userid": "74253750", "gameCostume": {"title": "new"}}

    selected = update_user._select_search_player([first, exact], "74253750")

    assert selected == exact


def test_select_search_player_falls_back_to_first_valid_player():
    fallback = {"userid": "12345678", "gameCostume": {"title": "fallback"}}

    selected = update_user._select_search_player([None, fallback], "74253750")

    assert selected == fallback


def test_select_search_player_returns_none_for_empty_payload():
    assert update_user._select_search_player([], "74253750") is None
