from __future__ import annotations

import re
import sre_parse
from typing import Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.consts import ENDSWITH_KEY, FULLMATCH_KEY, PREFIX_KEY, RAW_CMD_KEY, STARTSWITH_KEY
from nonebot.rule import CommandRule, EndswithRule, FullmatchRule, RegexRule, StartswithRule

from .config import CONFIG
from .taiko_commands import is_taiko_matcher, normalize_taiko_command

DENYLIST_MODULE_KEYWORDS = (
    "feature_handler",
    "blacklist_api",
    "blacklist_guard",
    "group_whitelist_guard",
)

GUARD_MODULE_HINTS = ("guard", "whitelist")
METHOD_NAME_STORAGE_PREFIX = "cmd::"
DISPLAY_ELLIPSIS = "…"
_MAX_LITERAL_OPTIONS = 32


def decode_method_name(method_name: str | None) -> str | None:
    if not method_name:
        return None
    text = str(method_name).strip()
    if not text.startswith(METHOD_NAME_STORAGE_PREFIX):
        return None
    decoded = text[len(METHOD_NAME_STORAGE_PREFIX) :].strip()
    return decoded or None


def _encode_method_name(method_name: str, max_len: int | None = None) -> str | None:
    text = method_name.strip()
    if not text:
        return None
    limit = max_len or CONFIG.method_name_max_len
    encoded = f"{METHOD_NAME_STORAGE_PREFIX}{text}"
    return encoded[:limit]


def _state_dict(state: Any) -> dict[str, Any]:
    if isinstance(state, dict):
        return state
    return {}


def _prefix_state(state: Any) -> dict[str, Any]:
    prefix = _state_dict(state).get(PREFIX_KEY)
    if isinstance(prefix, dict):
        return prefix
    return {}


def _matcher_rule_calls(matcher: Any) -> list[Any]:
    rule = getattr(matcher, "rule", None)
    checkers = getattr(rule, "checkers", None)
    if not checkers:
        return []
    return [getattr(checker, "call", None) for checker in checkers]


def _append_ellipsis_suffix(text: str) -> str:
    return f"{text}{DISPLAY_ELLIPSIS}" if text else ""


def _append_ellipsis_prefix(text: str) -> str:
    return f"{DISPLAY_ELLIPSIS}{text}" if text else ""


def _combine_options(left: set[str], right: set[str]) -> set[str] | None:
    combined = {f"{prefix}{suffix}" for prefix in left for suffix in right}
    if len(combined) > _MAX_LITERAL_OPTIONS:
        return None
    return combined


def _is_whitespace_literal(char: str) -> bool:
    return char.isspace()


def _token_is_boundary_anchor(op: Any, value: Any) -> bool:
    return op == sre_parse.AT and value in {
        sre_parse.AT_BEGINNING,
        sre_parse.AT_BEGINNING_STRING,
        sre_parse.AT_END,
        sre_parse.AT_END_STRING,
    }


def _token_is_whitespace(token: tuple[Any, Any]) -> bool:
    op, value = token
    if op == sre_parse.LITERAL:
        return _is_whitespace_literal(chr(value))
    if op == sre_parse.IN:
        return all(item[0] == sre_parse.CATEGORY and item[1] == sre_parse.CATEGORY_SPACE for item in value)
    if op == sre_parse.MAX_REPEAT:
        _, _, subpattern = value
        return bool(subpattern) and all(_token_is_whitespace(item) for item in subpattern)
    if op == sre_parse.SUBPATTERN:
        return all(_token_is_whitespace(item) for item in value[-1])
    return False


def _literal_options_from_sequence(
    tokens: list[tuple[Any, Any]],
    *,
    allow_optional_dynamic: bool,
    collapse_boundary_whitespace: bool,
) -> set[str] | None:
    options = {""}
    for token in tokens:
        part = _literal_options_from_token(
            token,
            allow_optional_dynamic=allow_optional_dynamic,
            collapse_boundary_whitespace=collapse_boundary_whitespace,
        )
        if part is None:
            return None
        combined = _combine_options(options, part)
        if combined is None:
            return None
        options = combined
    return options


def _literal_options_from_token(
    token: tuple[Any, Any],
    *,
    allow_optional_dynamic: bool,
    collapse_boundary_whitespace: bool,
) -> set[str] | None:
    op, value = token
    if _token_is_boundary_anchor(op, value):
        return {""}
    if op == sre_parse.AT:
        return {""}
    if op == sre_parse.LITERAL:
        char = chr(value)
        if collapse_boundary_whitespace and _is_whitespace_literal(char):
            return {""}
        return {char}
    if op == sre_parse.IN:
        if _token_is_whitespace(token):
            return {""}
        options = set()
        for item_op, item_value in value:
            if item_op != sre_parse.LITERAL:
                return None
            options.add(chr(item_value))
        return options
    if op == sre_parse.SUBPATTERN:
        return _literal_options_from_sequence(
            list(value[-1]),
            allow_optional_dynamic=allow_optional_dynamic,
            collapse_boundary_whitespace=collapse_boundary_whitespace,
        )
    if op == sre_parse.BRANCH:
        branch_options: set[str] = set()
        for branch in value[1]:
            branch_result = _literal_options_from_sequence(
                list(branch),
                allow_optional_dynamic=allow_optional_dynamic,
                collapse_boundary_whitespace=collapse_boundary_whitespace,
            )
            if branch_result is None:
                return None
            branch_options.update(branch_result)
            if len(branch_options) > _MAX_LITERAL_OPTIONS:
                return None
        return branch_options
    if op == sre_parse.MAX_REPEAT:
        min_repeat, max_repeat, subpattern = value
        if _token_is_whitespace(token):
            return {""}
        child_options = _literal_options_from_sequence(
            list(subpattern),
            allow_optional_dynamic=allow_optional_dynamic,
            collapse_boundary_whitespace=collapse_boundary_whitespace,
        )
        if min_repeat == 0 and max_repeat == 1:
            if child_options is None:
                return {""} if allow_optional_dynamic else None
            return child_options | {""}
        if min_repeat == 0 and allow_optional_dynamic:
            return {""}
        if min_repeat == 1 and max_repeat == 1:
            return child_options
        return None
    return None


def _boundary_options(tokens: list[tuple[Any, Any]], *, reverse: bool) -> tuple[set[str], bool]:
    options = {""}
    dynamic_seen = False
    iterable = list(reversed(tokens)) if reverse else list(tokens)

    for token in iterable:
        op, value = token
        if _token_is_boundary_anchor(op, value):
            continue
        part = _literal_options_from_token(
            token,
            allow_optional_dynamic=reverse and options == {""},
            collapse_boundary_whitespace=True,
        )
        if part is None:
            dynamic_seen = True
            break
        combined = _combine_options(part, options) if reverse else _combine_options(options, part)
        if combined is None:
            dynamic_seen = True
            break
        options = combined

    cleaned = {item.strip() for item in options if item and item.strip()}
    return cleaned, dynamic_seen


def _pick_matching_edge(options: set[str], text: str, *, from_start: bool, ignorecase: bool) -> str | None:
    if not options:
        return None

    compare_text = text.casefold() if ignorecase else text
    sorted_options = sorted(options, key=len, reverse=True)
    for option in sorted_options:
        compare_option = option.casefold() if ignorecase else option
        if from_start and compare_text.startswith(compare_option):
            return text[: len(option)]
        if not from_start:
            index = compare_text.rfind(compare_option)
            if index != -1:
                return text[index : index + len(option)]
    return None


def _has_substantial_text(text: str | None) -> bool:
    if not text:
        return False
    return any(char.isalnum() or "\u4e00" <= char <= "\u9fff" for char in text)


def _extract_exact_regex_text(tokens: list[tuple[Any, Any]], text: str, *, ignorecase: bool) -> str | None:
    options = _literal_options_from_sequence(
        tokens,
        allow_optional_dynamic=False,
        collapse_boundary_whitespace=False,
    )
    if not options:
        return None

    compare_text = text.casefold() if ignorecase else text
    for option in sorted(options, key=len, reverse=True):
        compare_option = option.casefold() if ignorecase else option
        if compare_text == compare_option:
            return text
    return None


def _extract_regex_display(rule_call: RegexRule, event: Any) -> str | None:
    get_plaintext = getattr(event, "get_plaintext", None)
    if not callable(get_plaintext):
        return None

    text = get_plaintext().strip()
    if not text:
        return None

    tokens = list(sre_parse.parse(rule_call.regex, rule_call.flags))
    anchor_start = any(
        op == sre_parse.AT and value in {sre_parse.AT_BEGINNING, sre_parse.AT_BEGINNING_STRING}
        for op, value in tokens
    )
    anchor_end = any(
        op == sre_parse.AT and value in {sre_parse.AT_END, sre_parse.AT_END_STRING}
        for op, value in tokens
    )
    if not anchor_start and not anchor_end:
        return None

    ignorecase = bool(rule_call.flags & re.IGNORECASE)
    exact = _extract_exact_regex_text(tokens, text, ignorecase=ignorecase)
    if exact and _has_substantial_text(exact):
        return exact

    prefix_options, _ = _boundary_options(tokens, reverse=False)
    suffix_options, _ = _boundary_options(tokens, reverse=True)
    prefix = _pick_matching_edge(prefix_options, text, from_start=True, ignorecase=ignorecase)
    suffix = _pick_matching_edge(suffix_options, text, from_start=False, ignorecase=ignorecase)

    if prefix and suffix and suffix == prefix and text == prefix:
        return prefix if _has_substantial_text(prefix) else None
    if prefix and suffix:
        display = f"{prefix}{DISPLAY_ELLIPSIS}{suffix}"
        return display if _has_substantial_text(prefix) or _has_substantial_text(suffix) else None
    if prefix:
        display = prefix if anchor_end and text == prefix else _append_ellipsis_suffix(prefix)
        return display if _has_substantial_text(prefix) else None
    if suffix:
        display = suffix if anchor_start and text == suffix else _append_ellipsis_prefix(suffix)
        return display if _has_substantial_text(suffix) else None
    return None


def extract_display_name(event: Any, matcher: Any, state: Any = None) -> str | None:
    prefix_state = _prefix_state(state)
    raw_command = str(prefix_state.get(RAW_CMD_KEY) or "").strip()
    if raw_command:
        return raw_command

    for rule_call in _matcher_rule_calls(matcher):
        if isinstance(rule_call, CommandRule):
            commands = list(getattr(rule_call, "cmds", ()) or ())
            if not commands:
                continue
            command = commands[0]
            command_text = " ".join(part for part in command if part).strip()
            if command_text:
                return command_text
            continue

        if isinstance(rule_call, FullmatchRule):
            get_plaintext = getattr(event, "get_plaintext", None)
            if not callable(get_plaintext):
                continue
            text = get_plaintext().strip()
            if text:
                return text
            matched = _state_dict(state).get(FULLMATCH_KEY)
            if isinstance(matched, str) and matched.strip():
                return matched.strip()
            continue

        if isinstance(rule_call, StartswithRule):
            matched = _state_dict(state).get(STARTSWITH_KEY)
            if isinstance(matched, str) and matched.strip():
                return _append_ellipsis_suffix(matched.strip())
            options = [item.strip() for item in getattr(rule_call, "msg", ()) if item and item.strip()]
            if options:
                return _append_ellipsis_suffix(options[0])
            continue

        if isinstance(rule_call, EndswithRule):
            matched = _state_dict(state).get(ENDSWITH_KEY)
            if isinstance(matched, str) and matched.strip():
                return _append_ellipsis_prefix(matched.strip())
            options = [item.strip() for item in getattr(rule_call, "msg", ()) if item and item.strip()]
            if options:
                return _append_ellipsis_prefix(options[0])
            continue

        if isinstance(rule_call, RegexRule):
            display = _extract_regex_display(rule_call, event)
            if display:
                return display

    return None


def extract_method_name(
    event: Any,
    matcher: Any | None = None,
    state: Any = None,
    max_len: int | None = None,
) -> str | None:
    if matcher is None:
        return None

    display_name = extract_display_name(event, matcher, state)
    if not display_name:
        return None
    return _encode_method_name(display_name, max_len=max_len)


def _matcher_module(matcher: Any) -> str:
    module = getattr(matcher, "__module__", "") or ""
    if module:
        return module

    matcher_cls = getattr(matcher, "__class__", None)
    if matcher_cls is not None:
        return getattr(matcher_cls, "__module__", "") or ""
    return ""


def _matcher_priority(matcher: Any) -> int:
    matcher_cls = getattr(matcher, "__class__", None)
    if matcher_cls is None:
        return 1
    return int(getattr(matcher_cls, "priority", 1))


def should_record(event: Any, matcher: Any) -> bool:
    if is_taiko_matcher(matcher):
        return normalize_taiko_command(event, matcher) is not None

    if not isinstance(event, GroupMessageEvent):
        return False

    module = _matcher_module(matcher)
    module_lower = module.lower()
    # Session routers, compatibility gates and diagnostic listeners are not
    # commands. Only explicitly registered community commands count.
    if str(getattr(matcher, "module_name", "") or module_lower).startswith("taiko_bot.runtime.community."):
        return False
    if any(keyword in module_lower for keyword in DENYLIST_MODULE_KEYWORDS):
        return False

    priority = _matcher_priority(matcher)
    if priority <= 1 and any(hint in module_lower for hint in GUARD_MODULE_HINTS):
        return False

    return extract_display_name(event, matcher) is not None


def build_record(
    event: Any,
    matcher: Any,
    state: Any = None,
) -> dict[str, Any] | None:
    taiko_match = normalize_taiko_command(event, matcher)
    if taiko_match is not None:
        method_name = _encode_method_name(taiko_match.display)
        if not method_name:
            return None
        return {
            "method_name": method_name,
            "group_id": taiko_match.group_id,
            "platform": taiko_match.platform,
            "normalized_command": taiko_match.canonical,
        }

    method_name = extract_method_name(event, matcher, state)
    if not method_name:
        return None
    return {
        "method_name": method_name,
        "group_id": str(getattr(event, "group_id", "") or "").strip() or None,
        "platform": None,
        "normalized_command": None,
    }
