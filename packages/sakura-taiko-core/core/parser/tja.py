"""从 TJA 谱面计算各 COURSE / 分歧路径的连打与气球元数据。

核心原则：
1. 逗号 `,` 才是小节结束；换行不是小节结束。
2. 保留音符片段之间的命令位置，支持小节内部 #BPMCHANGE / #DELAY。
3. #MEASURE 决定小节拍数；整小节所有音符字符共同决定 subdivision。
4. #BRANCHSTART 的 N/E/M 分别展开成独立时间轴计算。
5. BALLOON 按 TJA 源文件中的 7/9 出现顺序消费，并映射到对应分歧。
6. 气球记录持续时间、要求打速与给定 RPS 下的统计容量；容量统一向下取整。
7. 即使 BALLOON 头缺值，仍保留谱面中的 7/9 事件，并将 required_hits 记为 None。

默认 branch="M"，因此带分歧的 COURSE 顶层 roll_times / balloons 使用 M 路；
完整 N/E/M 结果位于 entry["branches"]。
"""

from __future__ import annotations

import math

import re

from dataclasses import dataclass

from typing import Dict, List, Optional, Sequence, Tuple, Union

_DRUMROLL = {"5", "6"}

_BALLOON = {"7", "9"}

_END = "8"

_BRANCHES = ("N", "E", "M")

_COURSE_KEY = {
    "easy": "easy",
    "normal": "normal",
    "hard": "hard",
    "oni": "oni",
    "ura": "ura",
    "edit": "ura",
    "0": "easy",
    "1": "normal",
    "2": "hard",
    "3": "oni",
    "4": "ura",
}

_NOTE_RE = re.compile(r"[0-9A-Za-z]")

@dataclass
class _NoteChunk:
    text: str

@dataclass
class _Command:
    name: str
    arg: str = ""

_Component = Union[_NoteChunk, _Command]

@dataclass
class _Measure:
    components: List[_Component]

@dataclass
class _CourseBlock:
    name: str
    balloons: List[int]
    chart_lines: List[str]
    style: str = "SINGLE"

def _strip_comment(line: str) -> str:
    idx = line.find("//")
    return line[:idx] if idx >= 0 else line

def _parse_float(text: str, default: float) -> float:
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
    if not m:
        return default
    try:
        return float(m.group(0))
    except ValueError:
        return default

def _parse_measure_ratio(text: str, default: float = 1.0) -> float:
    m = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if not m:
        return default
    numerator = int(m.group(1))
    denominator = int(m.group(2))
    return numerator / denominator if denominator else default

def _parse_balloons(line: str) -> List[int]:
    text = line.split(":", 1)[1].strip() if ":" in line else ""
    result: List[int] = []
    for item in text.split(","):
        item = item.strip()
        if re.fullmatch(r"\d+", item):
            result.append(int(item))
    return result

def _find_global_bpm(lines: Sequence[str]) -> float:
    for raw in lines:
        s = _strip_comment(raw).strip()
        if s.upper().startswith("BPM:"):
            return _parse_float(s.split(":", 1)[1], 120.0)
    return 120.0

def _split_courses(lines: Sequence[str]) -> List[_CourseBlock]:
    """提取 COURSE、BALLOON 和 #START/#END 之间的原始谱面行。"""
    blocks: List[_CourseBlock] = []
    course_name: Optional[str] = None
    balloons: List[int] = []
    chart_lines: List[str] = []
    style = "SINGLE"
    in_chart = False

    def flush(*, reset_course: bool = True) -> None:
        nonlocal course_name, balloons, chart_lines, style, in_chart
        if course_name is not None and chart_lines:
            blocks.append(_CourseBlock(course_name, list(balloons), list(chart_lines), style))
        if reset_course:
            course_name = None
            style = "SINGLE"
        balloons = []
        chart_lines = []
        in_chart = False

    for raw in lines:
        s = _strip_comment(raw).strip()
        if not s:
            continue
        upper = s.upper()

        if upper.startswith("COURSE:"):
            flush()
            course_name = s.split(":", 1)[1].strip().lower()
            continue

        if course_name is None:
            continue

        if upper.startswith("STYLE:") and not in_chart:
            # A TJA may place SINGLE and DOUBLE charts under one COURSE.
            # Keep both blocks available to callers, while parse_tja_roll_metadata
            # prefers SINGLE for single-player statistics.
            flush(reset_course=False)
            style = s.split(":", 1)[1].strip().upper() or "SINGLE"
            continue

        if upper.startswith("BALLOON:") and not in_chart:
            if style == "DOUBLE" and balloons:
                # Repeated metadata before a double chart is handled below;
                # keep the current block isolated from the next style.
                pass
            balloons = _parse_balloons(s)
            continue

        if upper.startswith("#START"):
            in_chart = True
            continue

        if upper.startswith("#END"):
            in_chart = False
            continue

        if in_chart:
            chart_lines.append(s)

    flush()
    return blocks

def _expand_branches(chart_lines: Sequence[str]) -> Tuple[bool, Dict[str, List[str]]]:
    """把带 #BRANCHSTART 的谱面展开为 N/E/M 三条独立路径。"""
    has_branch = any(
        _strip_comment(line).strip().upper().startswith("#BRANCHSTART")
        for line in chart_lines
    )
    if not has_branch:
        return False, {"M": list(chart_lines)}

    paths: Dict[str, List[str]] = {b: [] for b in _BRANCHES}
    in_branch = False
    active: Optional[str] = None

    for raw in chart_lines:
        s = _strip_comment(raw).strip()
        if not s:
            continue
        upper = s.upper()

        if upper.startswith("#BRANCHSTART"):
            in_branch = True
            active = None
            continue
        if in_branch and upper in {"#N", "#E", "#M"}:
            active = upper[1]
            continue
        if upper.startswith("#BRANCHEND"):
            in_branch = False
            active = None
            continue

        if in_branch:
            if active in paths:
                paths[active].append(s)
        else:
            for b in _BRANCHES:
                paths[b].append(s)

    return True, paths

def _map_balloons_to_branches(
    chart_lines: Sequence[str], balloon_values: Sequence[int]
) -> Tuple[bool, Dict[str, List[Optional[int]]], int]:
    """按 TJA 源文件中的“实际气球头”顺序映射 BALLOON 数值。

    重要语义：
    - 7/9 在没有长音符打开时才是新的气球头。
    - 已经处于 7/9 内部时再次出现相同字符，不创建新气球；尤其 9 的
      后续 9 可作为くすだま内部特殊时间标记。
    - 5/6/7 的重复字符（如 5558 / 7778）同样视作长音符内部标记。

    即使 BALLOON 头缺值，也会为实际气球头保留 ``None`` 占位。
    返回 (has_branch, branch_values, seen_balloon_heads)。
    """
    has_branch = False
    in_branch = False
    active: Optional[str] = None
    cursor = 0
    mapped: Dict[str, List[Optional[int]]] = {b: [] for b in _BRANCHES}
    open_long: Dict[str, Optional[str]] = {b: None for b in _BRANCHES}

    for raw in chart_lines:
        s = _strip_comment(raw).strip()
        if not s:
            continue
        upper = s.upper()

        if upper.startswith("#BRANCHSTART"):
            has_branch = True
            in_branch = True
            active = None
            continue
        if in_branch and upper in {"#N", "#E", "#M"}:
            active = upper[1]
            continue
        if upper.startswith("#BRANCHEND"):
            in_branch = False
            active = None
            continue
        if upper.startswith("#"):
            continue

        affected = [active] if in_branch and active in _BRANCHES else list(_BRANCHES)
        note_text = "".join(ch for ch in s if _NOTE_RE.fullmatch(ch))

        for ch in note_text:
            if ch in _DRUMROLL or ch in _BALLOON:
                starters = [b for b in affected if open_long[b] is None]
                # 同一个源文件位置只对应 BALLOON 列表中的一个值；公共区会
                # 将同一个值复制给 N/E/M，而不是消费三次。
                if ch in _BALLOON and starters:
                    value: Optional[int] = (
                        balloon_values[cursor] if cursor < len(balloon_values) else None
                    )
                    cursor += 1
                    for b in starters:
                        mapped[b].append(value)
                for b in starters:
                    open_long[b] = ch
                # 若已经打开相同长音符，则本字符属于内部/延续标记，不新开。
                continue

            if ch == _END:
                for b in affected:
                    open_long[b] = None

    return has_branch, mapped, cursor

def _parse_command(line: str) -> _Command:
    s = line.strip()
    if not s.startswith("#"):
        raise ValueError(f"not a TJA command: {line!r}")
    body = s[1:]
    if not body:
        return _Command("")
    parts = body.split(None, 1)
    name = parts[0].upper()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return _Command(name=name, arg=arg)

def _build_measures(chart_lines: Sequence[str]) -> List[_Measure]:
    """按逗号切分小节，同时保留命令在小节中的相对位置。"""
    measures: List[_Measure] = []
    components: List[_Component] = []
    note_buffer: List[str] = []

    def flush_note() -> None:
        nonlocal note_buffer
        if note_buffer:
            components.append(_NoteChunk("".join(note_buffer)))
            note_buffer = []

    def flush_measure(force: bool = False) -> None:
        nonlocal components
        flush_note()
        if components or force:
            measures.append(_Measure(list(components)))
        components = []

    for raw in chart_lines:
        s = _strip_comment(raw).strip()
        if not s:
            continue

        if s.startswith("#"):
            flush_note()
            components.append(_parse_command(s))
            continue

        # 一行可以包含一个或多个逗号；逗号才真正结束小节。
        for ch in s:
            if ch == ",":
                flush_measure(force=True)
            elif _NOTE_RE.fullmatch(ch):
                note_buffer.append(ch)
            else:
                # 空格等排版字符忽略；不把它们算作 subdivision。
                continue

    # 宽容处理：文件末尾若缺逗号，也不丢弃最后残留内容。
    if note_buffer or components:
        flush_measure()

    return measures

def _normalize_capacity_rates(rates: Sequence[float]) -> Tuple[float, ...]:
    result: List[float] = []
    seen = set()
    for raw in rates:
        rate = float(raw)
        if rate < 0:
            raise ValueError("capacity rates must be non-negative")
        if rate not in seen:
            seen.add(rate)
            result.append(rate)
    return tuple(result)

def _rate_key(rate: float) -> str:
    if float(rate).is_integer():
        return f"{int(rate)}rps"
    return f"{rate:g}rps"

def _balloon_capacity(duration: float, rate: float) -> int:
    """统计口径：capacity = floor(duration * rate)。

    虽然机台允许气球起点时刻立即输入第一打，但这里有意不使用 +1 的
    离散边界修正，以避免统计值在视觉上超过“R 打/s”的物理上限。
    """
    if duration <= 0 or rate <= 0:
        return 0
    # 减去极小 epsilon，避免浮点误差把理论上的整数边界推到下一整数。
    return max(0, math.floor(duration * rate + 1e-12))

def _summarize_events(
    rolls: Sequence[Dict[str, object]],
    balloon_events: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    known_required = [
        int(b["required_hits"])
        for b in balloon_events
        if b.get("required_hits") is not None
    ]
    unbreakable = [b for b in balloon_events if b.get("unbreakable") is True]
    unknown = [b for b in balloon_events if b.get("required_hits") is None]
    return {
        "roll_count": len(rolls),
        "roll_total_time": round(sum(float(r.get("duration", 0.0)) for r in rolls), 6),
        "balloon_count": len(balloon_events),
        "balloon_total_required_hits": sum(known_required),
        "balloon_unknown_required_count": len(unknown),
        "unbreakable_balloon_count": len(unbreakable),
        "has_unbreakable_balloon": bool(unbreakable),
    }

def _extract_chart_events(
    chart_lines: Sequence[str],
    global_bpm: float,
    balloon_values: Sequence[Optional[int]],
    *,
    capacity_rates: Sequence[float],
    machine_max_rate: float,
) -> Tuple[
    List[float],
    List[Dict[str, object]],
    List[Dict[str, object]],
    List[str],
]:
    """构建事件时间轴，提取 5/6 连打与 7/9 气球事件。"""
    measures = _build_measures(chart_lines)

    bpm = global_bpm
    measure_ratio = 1.0
    now = 0.0  # seconds

    open_char: Optional[str] = None
    open_start: Optional[float] = None
    open_balloon_required: Optional[int] = None
    open_internal_markers: List[float] = []
    balloon_cursor = 0

    rolls: List[Dict[str, object]] = []
    balloon_events: List[Dict[str, object]] = []
    warnings: List[str] = []

    rates = _normalize_capacity_rates(capacity_rates)
    max_rate = float(machine_max_rate)
    if max_rate < 0:
        raise ValueError("machine_max_rate must be non-negative")

    for measure_index, measure in enumerate(measures, start=1):
        total_slots = sum(
            len(comp.text)
            for comp in measure.components
            if isinstance(comp, _NoteChunk)
        )

        # 先看第一个音符之前是否有 #MEASURE；它决定当前整个小节的拍数。
        ratio_for_this_measure = measure_ratio
        seen_note = False
        for comp in measure.components:
            if isinstance(comp, _NoteChunk):
                if comp.text:
                    seen_note = True
                continue
            if comp.name == "MEASURE":
                parsed = _parse_measure_ratio(comp.arg, measure_ratio)
                if not seen_note:
                    ratio_for_this_measure = parsed
                else:
                    warnings.append(
                        f"measure {measure_index}: #MEASURE appears after note slots; "
                        "treated as applying to the next measure"
                    )

        if total_slots == 0:
            # 空小节：用当前 BPM 走完整个 measure；同时仍执行命令。
            for comp in measure.components:
                if not isinstance(comp, _Command):
                    continue
                if comp.name == "BPMCHANGE":
                    bpm = _parse_float(comp.arg, bpm)
                elif comp.name == "MEASURE":
                    measure_ratio = _parse_measure_ratio(comp.arg, measure_ratio)
                elif comp.name == "DELAY":
                    now += max(0.0, _parse_float(comp.arg, 0.0))
            if bpm > 0:
                now += ratio_for_this_measure * 240.0 / bpm
            continue

        beats_per_slot = 4.0 * ratio_for_this_measure / total_slots
        slots_seen = 0

        for comp in measure.components:
            if isinstance(comp, _Command):
                if comp.name == "BPMCHANGE":
                    new_bpm = _parse_float(comp.arg, bpm)
                    if new_bpm > 0:
                        bpm = new_bpm
                elif comp.name == "MEASURE":
                    parsed = _parse_measure_ratio(comp.arg, measure_ratio)
                    measure_ratio = parsed
                elif comp.name == "DELAY":
                    delay = _parse_float(comp.arg, 0.0)
                    if delay > 0:
                        now += delay
                continue

            for ch in comp.text:
                event_time = now

                if ch in _DRUMROLL or ch in _BALLOON:
                    if open_char is None:
                        open_char = ch
                        open_start = event_time
                        open_internal_markers = []
                        if ch in _BALLOON:
                            open_balloon_required = (
                                balloon_values[balloon_cursor]
                                if balloon_cursor < len(balloon_values)
                                else None
                            )
                            balloon_cursor += 1
                    elif ch == open_char:
                        # 5558 / 6668 / 7778 等重复字符属于长音符内部。
                        # くすだま(9) 的后续 9 还可表示内部特殊时间点。
                        if ch == "9":
                            open_internal_markers.append(event_time)
                    else:
                        warnings.append(
                            f"measure {measure_index}: long-note marker {ch} appears while "
                            f"{open_char} is still open; ignored as a new start"
                        )
                elif ch == _END and open_char is not None and open_start is not None:
                    duration = max(0.0, event_time - open_start)
                    if open_char in _DRUMROLL and duration > 0:
                        rolls.append(
                            {
                                "type": open_char,
                                "duration": round(duration, 6),
                                "start": round(open_start, 6),
                                "end": round(event_time, 6),
                            }
                        )
                    elif open_char in _BALLOON:
                        required_hits = open_balloon_required
                        capacities = {
                            _rate_key(rate): _balloon_capacity(duration, rate)
                            for rate in rates
                        }
                        capacity_at_max = _balloon_capacity(duration, max_rate)
                        required_rate = (
                            (required_hits / duration)
                            if required_hits is not None and duration > 0
                            else None
                        )
                        breakable = (
                            required_hits <= capacity_at_max
                            if required_hits is not None
                            else None
                        )
                        relative_markers = [
                            round(t - open_start, 6) for t in open_internal_markers
                        ]
                        balloon_events.append(
                            {
                                "type": open_char,
                                "required_hits": required_hits,
                                "duration": round(duration, 6),
                                "start": round(open_start, 6),
                                "end": round(event_time, 6),
                                "required_rate": (
                                    round(required_rate, 6)
                                    if required_rate is not None
                                    else None
                                ),
                                "capacities": capacities,
                                "machine_max_rate": max_rate,
                                "capacity_at_max_rate": capacity_at_max,
                                "theoretical_breakable": breakable,
                                "unbreakable": (
                                    (not breakable) if breakable is not None else None
                                ),
                                # 主要用于 type=9（くすだま）。不把这些内部 9
                                # 当成新气球；保留时间点便于以后做更细的演出分析。
                                "internal_markers": relative_markers,
                            }
                        )
                    open_char = None
                    open_start = None
                    open_balloon_required = None
                    open_internal_markers = []

                slots_seen += 1
                if bpm <= 0:
                    warnings.append(
                        f"measure {measure_index}: non-positive BPM {bpm}; slot time skipped"
                    )
                else:
                    now += beats_per_slot * 60.0 / bpm

        if slots_seen != total_slots:
            warnings.append(
                f"measure {measure_index}: internal slot mismatch {slots_seen}/{total_slots}"
            )

    if open_char is not None:
        warnings.append(f"unclosed roll/balloon marker {open_char} at chart end")

    if balloon_cursor < len(balloon_values):
        warnings.append(
            f"path has {len(balloon_values)} mapped BALLOON values but only "
            f"{balloon_cursor} balloon markers were consumed"
        )

    return [r["duration"] for r in rolls], rolls, balloon_events, warnings

def parse_tja_roll_metadata(
    tja_text: str,
    *,
    branch: str = "M",
    capacity_rates: Sequence[float] = (30.0, 35.0, 40.0, 60.0),
    machine_max_rate: float = 60.0,
) -> Dict[str, Dict[str, object]]:
    """解析 TJA，返回各 COURSE 的连打与气球元数据。

    参数
    ----
    tja_text:
        已解码的 TJA 文本。
    branch:
        对带分歧 COURSE，顶层字段采用哪条路径。可选 N / E / M，默认 M。
    capacity_rates:
        为每个气球计算统计容量的打速（打/s）。容量定义为
        ``floor(duration * rate)``。默认计算 30/35/40/60 rps。
    machine_max_rate:
        机台理论最高打速，用于 ``theoretical_breakable`` 判断。默认 60 rps。

    兼容字段
    --------
    ``roll_times`` 与 ``balloons`` 保持旧版语义。

    新增字段
    --------
    ``balloon_events``：每个实际 7/9 的持续时间、required_hits、required_rate、
    capacities、theoretical_breakable 等。
    ``summary``：roll/balloon 数量、总时长、不可击破气球数量等摘要。
    """
    selected = branch.upper()
    if selected not in _BRANCHES:
        raise ValueError("branch must be one of 'N', 'E', 'M'")

    rates = _normalize_capacity_rates(capacity_rates)
    max_rate = float(machine_max_rate)
    if max_rate < 0:
        raise ValueError("machine_max_rate must be non-negative")

    lines = tja_text.replace("\ufeff", "").splitlines()
    global_bpm = _find_global_bpm(lines)
    courses: Dict[str, Dict[str, object]] = {}

    for block in _split_courses(lines):
        key = _COURSE_KEY.get(block.name, block.name)
        if block.style == "DOUBLE" and key in courses:
            continue
        has_branch, paths = _expand_branches(block.chart_lines)
        _, balloon_map, seen_balloons = _map_balloons_to_branches(
            block.chart_lines, block.balloons
        )

        if has_branch:
            branch_results: Dict[str, Dict[str, object]] = {}
            for b in _BRANCHES:
                roll_times, rolls, balloon_events, warnings = _extract_chart_events(
                    paths[b],
                    global_bpm,
                    balloon_map[b],
                    capacity_rates=rates,
                    machine_max_rate=max_rate,
                )
                branch_results[b] = {
                    "roll_times": roll_times,
                    "rolls": rolls,
                    # 兼容旧版：只返回 TJA 中实际有数值的 BALLOON 打数。
                    "balloons": [v for v in balloon_map[b] if v is not None],
                    "balloon_events": balloon_events,
                    "summary": _summarize_events(rolls, balloon_events),
                    "warnings": warnings,
                }

            chosen = branch_results[selected]
            entry: Dict[str, object] = {
                "roll_times": list(chosen["roll_times"]),
                "rolls": list(chosen["rolls"]),
                "balloons": list(chosen["balloons"]),
                "balloon_events": list(chosen["balloon_events"]),
                "summary": dict(chosen["summary"]),
                "balloons_all": list(block.balloons),
                "selected_branch": selected,
                "branches": branch_results,
            }
        else:
            mapped = balloon_map["M"]
            roll_times, rolls, balloon_events, warnings = _extract_chart_events(
                paths["M"],
                global_bpm,
                mapped,
                capacity_rates=rates,
                machine_max_rate=max_rate,
            )
            entry = {
                "roll_times": roll_times,
                "rolls": rolls,
                "balloons": [v for v in mapped if v is not None],
                "balloon_events": balloon_events,
                "summary": _summarize_events(rolls, balloon_events),
                "warnings": warnings,
            }

        if seen_balloons != len(block.balloons):
            entry.setdefault("warnings", [])
            entry["balloon_warning"] = (
                f"BALLOON has {len(block.balloons)} values but chart contains "
                f"{seen_balloons} balloon markers (7/9) in source order"
            )

        courses[key] = entry

    return courses
