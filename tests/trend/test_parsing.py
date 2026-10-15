import pytest
import numpy as np
from taiko_bot.runtime.player.center.trend_support import parsing as taiko
from taiko_bot.runtime.player.center.trend_support.score_calculator import _smooth_playtrend_rate_series

def _load_taiko_module():return taiko

def test_parse_playtrend_args_defaults():
    taiko = _load_taiko_module()
    args = taiko._parse_playtrend_args("")
    assert args == {
        "N": 20,
        "max_points": 80,
        "bar_mode": False,
        "show_all": False,
        "selected_dim": None,
    }

def test_parse_playtrend_args_custom_values():
    taiko = _load_taiko_module()
    args = taiko._parse_playtrend_args("30 120 体力 -a -b")
    assert args["N"] == 30
    assert args["max_points"] == 120
    assert args["selected_dim"] == "体力"
    assert args["show_all"] is True
    assert args["bar_mode"] is True

def test_parse_playtrend_args_dim_flag():
    taiko = _load_taiko_module()
    args = taiko._parse_playtrend_args("--dim 精度 25")
    assert args["N"] == 25
    assert args["selected_dim"] == "精度力"

def test_parse_v2_trend_args_uses_v2_dimensions_without_counting_version_digit():
    taiko = _load_taiko_module()
    version, arg_text = taiko._extract_rating_version("v2 手速 30 120")

    assert version == "v2"
    assert taiko._parse_playtrend_args(
        arg_text, dim_aliases=taiko.V2_TREND_DIM_ALIASES
    ) == {
        "N": 30,
        "max_points": 120,
        "bar_mode": False,
        "show_all": False,
        "selected_dim": "手速",
    }

def test_explicit_v1_is_removed_and_preserves_default_trend_args():
    taiko = _load_taiko_module()
    version, arg_text = taiko._extract_rating_version("v1")

    assert version == "v1"
    assert taiko._parse_trend_args(arg_text) == taiko._parse_trend_args("")

def test_v1_and_v2_cannot_be_combined():
    taiko = _load_taiko_module()
    with pytest.raises(ValueError, match="不能同时"):
        taiko._extract_rating_version("v1 v2")

def test_parse_playtrend_args_invalid_token():
    taiko = _load_taiko_module()
    with pytest.raises(ValueError) as exc:
        taiko._parse_playtrend_args("foo")
    assert taiko.PLAYTREND_USAGE_MESSAGE in str(exc.value)

def test_parse_playtrend_args_max_points_range():
    taiko = _load_taiko_module()
    with pytest.raises(ValueError, match="曲数点数"):
        taiko._parse_playtrend_args("20 501")

def test_smooth_playtrend_rate_series_linear_growth():
    x = np.array([0.0, 10.0, 20.0, 30.0])
    y = np.array([1.0, 2.0, 3.0, 4.0])
    rate_x, rate_y = _smooth_playtrend_rate_series(x, y, dense_points=40)
    assert rate_x.size == 40
    assert rate_y.min() > 0.05
    assert rate_y.max() < 0.15
