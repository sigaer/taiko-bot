"""BXX compares numerical update measurements, never raw historical scores."""
from taiko_bot.runtime.player.bxx_summary import update_diff, growth
from taiko_application.score.b30_single import B30SingleRenderer


def test_format_rating_delta_uses_adaptive_precision():
    for value, expected in [(0.0, '+0.00'), (0.044273, '+0.04'),
                            (0.004273, '+0.004'), (0.000897, '+0.0009'),
                            (0.00001, '+<0.0001')]:
        assert B30SingleRenderer._format_rating_delta(None, value) == expected


def test_missing_previous_does_not_mark_every_song_new():
    assert update_diff([(10, {'song_no': 1, 'level': 4})], {'体力': 10}, 10, {}) == (set(), {}, {}, 0.0)


def test_unchanged_total_still_detects_new_top_and_dimension_change():
    previous = {'rating': 10, 'dimensions': {'体力': 9}, 'top': [[1, 4, 10], [2, 4, 10]]}
    top = [(10, {'song_no': 1, 'level': 4}), (10, {'song_no': 3, 'level': 4})]
    new, improved, dimensions, total = update_diff(top, {'体力': 10}, 10, {'previous': previous})
    assert new == {(3, 4)} and improved == {} and dimensions == {'体力': 1} and total == 0


def test_single_song_increase_and_signed_total():
    previous = {'rating': 11, 'dimensions': {'体力': 10}, 'top': [[1, 4, 10]]}
    top = [(10.25, {'song_no': 1, 'level': 4})]
    new, improved, dimensions, total = update_diff(top, {'体力': 9.5}, 10.75, {'previous': previous})
    assert new == set() and improved == {(1, 4): 0.25}
    assert dimensions == {'体力': -0.5} and total == -0.25


def test_legacy_previous_numbers_do_not_fabricate_new_songs():
    previous = {'rating': 10, 'dimensions': {'体力': 9}, 'top': None}
    result = update_diff([(11, {'song_no': 1, 'level': 4})], {'体力': 10}, 11, {'previous': previous})
    assert result == (set(), {}, {'体力': 1}, 1)


def test_growth_is_current_minus_window_start_not_range_extrema():
    baseline = {'rating': 10, 'dimensions': {'体力': 9}}
    assert growth({'体力': 8}, 11, {'baseline': baseline}) == {'体力': -1, '综合Rating': 1}
