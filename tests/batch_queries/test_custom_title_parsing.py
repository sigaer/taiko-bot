import pytest
from taiko_bot.runtime.player.center.display_host_support import custom_title

@pytest.mark.parametrize(
    "command",
    ["加称号", "添加称号", "追加称号", "自定义称号", "ttitle", "TTITLE"],
)
def test_parse_custom_title_command_supports_all_aliases_and_default_oni(command):
    parsed = custom_title.parse_custom_title_command(
        f"{command}测试称号 to 夏祭り"
    )
    assert parsed == custom_title.ParsedCustomTitleCommand("测试称号", "夏祭り", 4)

def test_parse_custom_title_command_accepts_compact_to_separator():
    command = "添加称号 大家的太鼓·太棒了！to 合唱庆节"

    assert custom_title.CUSTOM_TITLE_COMMAND_PATTERN.match(command)
    assert custom_title.parse_custom_title_command(command) == (
        custom_title.ParsedCustomTitleCommand(
            "大家的太鼓·太棒了!",
            "合唱庆节",
            4,
        )
    )

@pytest.mark.parametrize("label,level", [("里", 5), ("表", 4), ("松", 3), ("竹", 2), ("梅", 1)])
@pytest.mark.parametrize("separator", ["", " "])
def test_parse_custom_title_command_maps_difficulties(label, level, separator):
    parsed = custom_title.parse_custom_title_command(
        f"ttitle无空格称号 to {label}{separator}夏祭り"
    )
    assert parsed == custom_title.ParsedCustomTitleCommand("无空格称号", "夏祭り", level)

@pytest.mark.parametrize(
    "label,achievement_type",
    [("过关", "clear"), ("全连", "full_combo"), ("全良", "all_perfect")],
)
def test_parse_custom_title_command_maps_achievement(label, achievement_type):
    parsed = custom_title.parse_custom_title_command(
        f"加称号 成就称号 to 里 夏祭り {label}"
    )
    assert parsed == custom_title.ParsedCustomTitleCommand(
        "成就称号",
        "夏祭り",
        5,
        achievement_type,
    )


def test_validate_custom_title_normalizes_and_limits_length():
    assert custom_title.validate_custom_title_name("  Ａ　称号  ") == ("A 称号", "a 称号")
    with pytest.raises(custom_title.CustomTitleValidationError):
        custom_title.validate_custom_title_name("x" * 31)
    with pytest.raises(custom_title.CustomTitleValidationError):
        custom_title.validate_custom_title_name("坏\u0000称号")
