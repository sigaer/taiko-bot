from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Set, Tuple

from .client import (
    HirobaClient,
    HirobaError,
    HirobaLoginCard,
    HirobaSessionExpiredError,
    HirobaUpdateScoreError,
)
from .cooldown import acquire_hiroba_sync_slot, peek_hiroba_sync_cooldown
from .credentials import delete_hiroba_token
from .normalize import build_userdata
from .parser import (
    DEFAULT_HIROBA_SYNC_LEVELS,
    HirobaScoreDetail,
    enumerate_fetch_tasks,
    filter_song_refs_by_levels,
    merge_song_refs,
    parse_mypage_achievement,
    parse_profile,
    parse_score_detail,
    parse_score_list_page,
)
from ..userdata_storage import save_userdata

ProgressCallback = Optional[Callable[..., None]]


def _parse_sync_levels(raw: str) -> Optional[Set[int]]:
    text = str(raw or "").strip().lower()
    if not text or text in {"all", "*"}:
        return None
    levels: Set[int] = set()
    for part in text.replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue
        levels.add(int(token))
    return levels or None


def resolve_hiroba_sync_levels(levels: Optional[Set[int]] = None) -> Optional[Set[int]]:
    if levels is not None:
        return levels or None
    env_levels = _parse_sync_levels(os.getenv("HIROBA_SYNC_LEVELS", "4,5"))
    if env_levels is None:
        return None
    return set(env_levels)


def _level_label(levels: Optional[Set[int]]) -> str:
    if levels is None:
        return "全部难度"
    names = []
    for level in sorted(levels):
        if level == 4:
            names.append("鬼")
        elif level == 5:
            names.append("里")
        else:
            names.append(f"L{level}")
    return "/".join(names) if names else "全部难度"


def _report(progress: ProgressCallback, message: str, *, force: bool = False) -> None:
    if not progress:
        return
    try:
        progress(message, force=force)
    except TypeError:
        progress(message)


def _fetch_report_milestones(total: int) -> List[int]:
    if total <= 0:
        return []
    if total <= 4:
        return list(range(1, total + 1))
    return sorted(
        {
            max(1, total // 4),
            max(1, total // 2),
            max(1, (3 * total) // 4),
            total,
        }
    )


def _login_hiroba_client(
    client: HirobaClient,
    *,
    email: Optional[str],
    password: Optional[str],
    taiko_no: Optional[str],
) -> None:
    if not email or not password:
        raise HirobaError("email/password or token is required")
    client.login(email, password, taiko_no=taiko_no)


def sync_hiroba_userdata(
    email: Optional[str] = None,
    password: Optional[str] = None,
    *,
    taiko_no: Optional[str] = None,
    token: Optional[str] = None,
    levels: Optional[Set[int]] = None,
    max_workers: int = 4,
    request_delay: float = 0.15,
    progress: ProgressCallback = None,
) -> str:
    requested_taiko_no = str(taiko_no or "").strip()
    if requested_taiko_no:
        cooldown_msg = peek_hiroba_sync_cooldown(requested_taiko_no)
        if cooldown_msg:
            raise HirobaError(cooldown_msg)

    sync_levels = resolve_hiroba_sync_levels(levels)
    level_label = _level_label(sync_levels)
    if taiko_no and not token:
        delete_hiroba_token(taiko_no)
    cached_token = token
    client = HirobaClient(token=cached_token)
    relogin_attempted = False

    def _relogin(reason: str) -> None:
        nonlocal client, relogin_attempted
        if relogin_attempted:
            raise HirobaError(reason)
        relogin_attempted = True
        client = HirobaClient()
        _login_hiroba_client(
            client,
            email=email,
            password=password,
            taiko_no=taiko_no,
        )

    def _run_with_relogin(action, *, reason: str):
        try:
            return action()
        except HirobaSessionExpiredError:
            _relogin(reason)
            return action()

    def _run_update_score_with_recovery() -> None:
        try:
            _run_with_relogin(
                lambda: client.update_score(),
                reason="检测到 Hiroba 登录态已失效，正在重新登录...",
            )
            return
        except HirobaUpdateScoreError as error:
            if error.result != "701":
                raise
            if requested_taiko_no:
                delete_hiroba_token(requested_taiko_no)
            _relogin("检测到 Hiroba 同步状态异常(701)，正在重新登录后重试...")
            client.update_score()

    _login_hiroba_client(
        client,
        email=email,
        password=password,
        taiko_no=taiko_no,
    )

    _run_update_score_with_recovery()

    mypage_html = _run_with_relogin(
        lambda: client.fetch_mypage(),
        reason="读取个人资料时发现 Hiroba 登录态已失效，正在重新登录...",
    )
    profile = parse_profile(mypage_html)
    achievement = parse_mypage_achievement(mypage_html)
    if taiko_no and profile.taiko_no != str(taiko_no):
        raise HirobaError(
            f"Expected taiko_no {taiko_no}, but login resolved to {profile.taiko_no}"
        )
    taiko_no = profile.taiko_no

    cooldown_msg = acquire_hiroba_sync_slot(taiko_no)
    if cooldown_msg:
        raise HirobaError(cooldown_msg)

    genre_pages = []
    for genre in range(1, 9):
        genre_pages.append(
            parse_score_list_page(
                _run_with_relogin(
                    lambda genre=genre: client.fetch_score_list(genre),
                    reason="读取成绩列表时发现 Hiroba 登录态已失效，正在重新登录...",
                )
            )
        )
        time.sleep(request_delay)
    merged = merge_song_refs(genre_pages)
    filtered = filter_song_refs_by_levels(merged, sync_levels) if sync_levels else merged
    tasks = enumerate_fetch_tasks(filtered, levels=sync_levels)
    total = len(tasks)
    _report(progress, f"已识别 {total} 张游玩记录谱面", force=True)

    details: List[HirobaScoreDetail] = []
    if total == 0:
        userdata = build_userdata(profile, details, achievement)
        save_userdata(taiko_no, userdata, source="hiroba")
        _report(progress, "同步完成", force=True)
        return taiko_no

    def _fetch_one(task: Tuple[str, int]) -> Optional[HirobaScoreDetail]:
        song_no, level = task
        html = client.fetch_score_detail(song_no, level)
        time.sleep(request_delay)
        return parse_score_detail(html, song_no, level)

    completed = 0
    report_milestones = _fetch_report_milestones(total)
    next_milestone_index = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, task): task for task in tasks}
        for future in as_completed(futures):
            completed += 1
            if (
                next_milestone_index < len(report_milestones)
                and completed >= report_milestones[next_milestone_index]
            ):
                _report(
                    progress,
                    f"正在拉取谱面详情 {completed}/{total}（{level_label}）...",
                    force=True,
                )
                next_milestone_index += 1
            try:
                detail = future.result()
            except Exception:
                continue
            if detail is not None:
                details.append(detail)

    userdata = build_userdata(profile, details, achievement)
    save_userdata(taiko_no, userdata, source="hiroba")
    _report(progress, "同步完成", force=True)
    return taiko_no


def discover_hiroba_playable_cards(
    email: str,
    password: str,
) -> List[HirobaLoginCard]:
    client = HirobaClient()
    cards = client.list_login_cards(email, password)
    return [card for card in cards if card.has_play_data and card.taiko_no]


def sync_multiple_hiroba_userdatas(
    email: str,
    password: str,
    *,
    target_taiko_no: Optional[str] = None,
    levels: Optional[Set[int]] = None,
    max_workers: int = 4,
    request_delay: float = 0.15,
    progress: ProgressCallback = None,
) -> List[str]:
    playable_cards = discover_hiroba_playable_cards(email, password)
    if not playable_cards:
        raise HirobaError("该 Bandai Namco ID 下没有可同步的 Hiroba 太鼓番。")

    selected_cards = playable_cards
    if target_taiko_no:
        target = str(target_taiko_no).strip()
        selected_cards = [card for card in playable_cards if card.taiko_no == target]
        if not selected_cards:
            choices = " / ".join(
                f"{card.taiko_no}({card.display_name})" if card.display_name else card.taiko_no
                for card in playable_cards
            )
            raise HirobaError(
                f"该 Bandai Namco ID 下未找到太鼓番 {target}。"
                + (f"可用太鼓番：{choices}" if choices else "")
            )

    synced_ids: List[str] = []
    for card in selected_cards:
        taiko_no = sync_hiroba_userdata(
            email,
            password,
            taiko_no=card.taiko_no,
            levels=levels,
            max_workers=max_workers,
            request_delay=request_delay,
            progress=progress,
        )
        synced_ids.append(taiko_no)
    return synced_ids
