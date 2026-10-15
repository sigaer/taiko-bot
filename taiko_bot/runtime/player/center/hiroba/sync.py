from __future__ import annotations


import logging

import os

import threading

import time

from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .client import HirobaClient, HirobaError, HirobaLoginCard, HirobaProfilePrivateError, HirobaSessionExpiredError, HirobaUpdateScoreError

from .cooldown import acquire_hiroba_sync_slot, peek_hiroba_sync_cooldown, release_hiroba_sync_slot

from .credentials import delete_hiroba_token

from .normalize import build_userdata

from .parser import DEFAULT_HIROBA_SYNC_LEVELS, HirobaProfile, HirobaScoreDetail, enumerate_fetch_tasks, filter_song_refs_by_levels, merge_song_refs, parse_mypage_achievement, parse_profile, parse_score_detail, parse_score_list_page

from .service import login_hiroba_service_client

from ..userdata_storage import save_userdata

ProgressCallback = Optional[Callable[..., None]]

logger = logging.getLogger(__name__)

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

def _sync_duration_hint(total: int) -> str:
    if total >= 1200:
        return "，谱面较多，完整同步通常需要 5-7 分钟"
    if total >= 800:
        return "，谱面较多，完整同步通常需要数分钟"
    return ""

def _build_thread_local_detail_client_factory(
    token: str,
    *,
    timeout: int,
) -> Callable[[bool], HirobaClient]:
    local_state = threading.local()
    normalized_token = str(token or "").strip()

    def _get_client(reset: bool = False) -> HirobaClient:
        client = None if reset else getattr(local_state, "client", None)
        if client is None:
            client = HirobaClient(token=normalized_token or None, timeout=timeout)
            local_state.client = client
        return client

    return _get_client

def _fetch_score_detail_with_retry(
    get_client: Callable[[bool], HirobaClient],
    task: Tuple[str, int],
    *,
    request_delay: float,
    fetch_kwargs: Optional[Dict[str, Any]] = None,
    max_attempts: int = 3,
) -> Optional[HirobaScoreDetail]:
    song_no, level = task
    last_error: Optional[Exception] = None
    effective_fetch_kwargs = dict(fetch_kwargs or {})
    for attempt in range(1, max_attempts + 1):
        try:
            html = get_client(reset=attempt > 1).fetch_score_detail(
                song_no,
                level,
                **effective_fetch_kwargs,
            )
            time.sleep(request_delay)
            return parse_score_detail(html, song_no, level)
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise
            time.sleep(min(0.4 * attempt, 1.2))
    if last_error is not None:
        raise last_error
    return None

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

def _save_hiroba_userdata_from_pages(
    *,
    taiko_no: str,
    profile: HirobaProfile,
    achievement: Dict[str, object],
    genre_pages: List[Dict[str, Any]],
    get_detail_client: Callable[[bool], HirobaClient],
    detail_fetch_kwargs: Optional[Dict[str, Any]] = None,
    levels: Optional[Set[int]],
    max_workers: int,
    request_delay: float,
    progress: ProgressCallback,
    publication_store=None,
) -> str:
    level_label = _level_label(levels)
    merged = merge_song_refs(genre_pages)
    filtered = filter_song_refs_by_levels(merged, levels) if levels else merged
    tasks = enumerate_fetch_tasks(filtered, levels=levels)
    fallback_crowns = {
        (song_no, level): crown
        for song_no, ref in filtered.items()
        for level, crown in ref.crowns.items()
    }
    total = len(tasks)
    _report(
        progress,
        f"已识别 {total} 张游玩记录谱面{_sync_duration_hint(total)}",
        force=True,
    )

    details: List[HirobaScoreDetail] = []
    if total == 0:
        userdata = build_userdata(profile, details, achievement)
        save_userdata(taiko_no, userdata, source="hiroba", **({"publication_store": publication_store} if publication_store is not None else {}))
        _report(progress, "同步完成", force=True)
        return taiko_no

    def _fetch_one(task: Tuple[str, int]) -> Optional[HirobaScoreDetail]:
        return _fetch_score_detail_with_retry(
            get_detail_client,
            task,
            request_delay=request_delay,
            fetch_kwargs=detail_fetch_kwargs,
        )

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
                )
                next_milestone_index += 1
            try:
                detail = future.result()
            except Exception as exc:
                song_no, level = futures[future]
                logger.warning(
                    "hiroba detail fetch failed for taiko_no=%s song_no=%s level=%s: %s",
                    taiko_no,
                    song_no,
                    level,
                    exc,
                )
                continue
            if detail is not None:
                fallback_crown = fallback_crowns.get((detail.song_no, detail.level))
                if fallback_crown and not detail.crown:
                    detail.crown = fallback_crown
                details.append(detail)

    userdata = build_userdata(profile, details, achievement)
    save_userdata(taiko_no, userdata, source="hiroba", **({"publication_store": publication_store} if publication_store is not None else {}))
    _report(progress, "同步完成", force=True)
    return taiko_no

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
    publication_store=None,
) -> str:
    requested_taiko_no = str(taiko_no or "").strip()
    if requested_taiko_no:
        cooldown_msg = peek_hiroba_sync_cooldown(requested_taiko_no)
        if cooldown_msg:
            raise HirobaError(cooldown_msg)

    sync_levels = resolve_hiroba_sync_levels(levels)
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
    try:
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

        detail_token = str(client.token or "").strip()
        if not detail_token:
            raise HirobaError("Missing Hiroba token before fetching score details")
        get_detail_client = _build_thread_local_detail_client_factory(
            detail_token,
            timeout=client.timeout,
        )
        return _save_hiroba_userdata_from_pages(
            taiko_no=taiko_no,
            profile=profile,
            achievement=achievement,
            genre_pages=genre_pages,
            get_detail_client=get_detail_client,
            levels=sync_levels,
            max_workers=max_workers,
            request_delay=request_delay,
            progress=progress,
            publication_store=publication_store,
        )
    except Exception:
        release_hiroba_sync_slot(taiko_no)
        raise

def sync_public_hiroba_userdata(
    taiko_no: str,
    *,
    levels: Optional[Set[int]] = None,
    max_workers: int = 4,
    request_delay: float = 0.15,
    progress: ProgressCallback = None,
    publication_store=None,
) -> str:
    requested_taiko_no = str(taiko_no or "").strip()
    if not requested_taiko_no:
        raise HirobaError("taiko_no is required")

    cooldown_msg = peek_hiroba_sync_cooldown(requested_taiko_no)
    if cooldown_msg:
        raise HirobaError(cooldown_msg)

    sync_levels = resolve_hiroba_sync_levels(levels)
    _report(progress, "正在通过 Hiroba 服务账号读取公开成绩...", force=True)
    client = login_hiroba_service_client(timeout=30)
    profile_html = client.fetch_public_profile(requested_taiko_no)
    profile = parse_profile(profile_html)
    achievement = parse_mypage_achievement(profile_html)
    taiko_no = profile.taiko_no

    cooldown_msg = acquire_hiroba_sync_slot(taiko_no)
    if cooldown_msg:
        raise HirobaError(cooldown_msg)
    try:
        genre_pages = []
        for genre in range(1, 9):
            genre_pages.append(
                parse_score_list_page(client.fetch_public_score_list(taiko_no, genre))
            )
            time.sleep(request_delay)

        detail_token = str(client.token or "").strip()
        if not detail_token:
            raise HirobaError(
                "Missing Hiroba service token before fetching public score details"
            )
        get_detail_client = _build_thread_local_detail_client_factory(
            detail_token,
            timeout=client.timeout,
        )
        return _save_hiroba_userdata_from_pages(
            taiko_no=taiko_no,
            profile=profile,
            achievement=achievement,
            genre_pages=genre_pages,
            get_detail_client=get_detail_client,
            detail_fetch_kwargs={"taiko_no": taiko_no, "other": True, "mode": 0},
            levels=sync_levels,
            max_workers=max_workers,
            request_delay=request_delay,
            progress=progress,
            publication_store=publication_store,
        )
    except Exception:
        release_hiroba_sync_slot(taiko_no)
        raise

def sync_bound_hiroba_userdata(
    taiko_no: str,
    *,
    email: Optional[str] = None,
    password: Optional[str] = None,
    levels: Optional[Set[int]] = None,
    max_workers: int = 4,
    request_delay: float = 0.15,
    progress: ProgressCallback = None,
    publication_store=None,
) -> str:
    if email and password:
        _report(progress, "检测到已保存 Hiroba 凭据，优先使用凭据登录同步完整成绩...", force=True)
        return sync_hiroba_userdata(
            email,
            password,
            taiko_no=taiko_no,
            levels=levels,
            max_workers=max_workers,
            request_delay=request_delay,
            progress=progress,
            publication_store=publication_store,
        )
    try:
        return sync_public_hiroba_userdata(
            taiko_no,
            levels=levels,
            max_workers=max_workers,
            request_delay=request_delay,
            progress=progress,
            publication_store=publication_store,
        )
    except HirobaProfilePrivateError as error:
        raise HirobaError(
            f"Hiroba 账号 {taiko_no} 当前为非公开资料，服务账号无法读取公开成绩。"
            f"如需继续同步，请发送“绑定hiroba 邮箱 密码 {taiko_no}”。"
        ) from error
    except HirobaError:
        raise

def discover_hiroba_playable_cards(
    email: str,
    password: str,
) -> List[HirobaLoginCard]:
    client = HirobaClient()
    cards = client.list_login_cards(email, password)
    return [card for card in cards if card.has_play_data and card.taiko_no]
