from sakura_taiko_core.chart.visibility import is_song_publicly_visible

def test_public_visibility_policy():
    assert not is_song_publicly_visible({'id': 1429})
    assert not is_song_publicly_visible({'id': 987})
    assert is_song_publicly_visible({'id': 153})
