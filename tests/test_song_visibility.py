from plugins.utils.song_visibility import (
    DOWN_SHELF_OVERRIDE_SONG_IDS,
    HIDDEN_SONG_IDS,
    is_song_id_publicly_visible,
    load_public_song_ids,
)


def test_public_song_ids_exclude_double_hidden_and_deleted_overrides():
    public_ids = load_public_song_ids()

    assert 900 not in public_ids
    assert 1429 not in public_ids
    assert 987 not in public_ids
    assert 153 in public_ids


def test_explicit_visibility_overrides_are_applied():
    assert HIDDEN_SONG_IDS == {1429}
    assert DOWN_SHELF_OVERRIDE_SONG_IDS == {231, 678, 987, 1167, 1200}

    assert not is_song_id_publicly_visible(1429)
    assert not is_song_id_publicly_visible(987)
    assert not is_song_id_publicly_visible(900)
    assert is_song_id_publicly_visible(153)
