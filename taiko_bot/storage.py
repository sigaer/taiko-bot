from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .settings import Settings, ensure_runtime_dirs, get_settings


def _default_draw_guess_db() -> Dict[str, Any]:
    return {"next_id": 1, "records": [], "user_guess_stats": {}}


def _default_config() -> Dict[str, Any]:
    return {
        "cookie": "",
        "bemanicn": {"email": "", "password": ""},
        "meta": {"created_at": datetime.now().isoformat(timespec="seconds")},
    }


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def ensure_storage_layout(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    ensure_runtime_dirs(cfg)
    compatibility_links = {
        cfg.root_dir / "userdata": cfg.userdata_dir,
        cfg.root_dir / "data": cfg.runtime_data_dir,
        cfg.root_dir / "logs": cfg.logs_dir,
        cfg.root_dir / "output": cfg.output_dir,
        cfg.root_dir / "secrets": cfg.secrets_dir,
        cfg.root_dir / "config.json": cfg.config_path,
    }
    for link_path, target_path in compatibility_links.items():
        if link_path.exists() or link_path.is_symlink():
            continue
        try:
            link_path.symlink_to(target_path)
        except OSError:
            # Filesystems without symlink support fall back to the storage path directly.
            pass
    if not cfg.config_path.exists():
        write_json_atomic(cfg.config_path, _default_config())
    if not cfg.multi_bind_path.exists():
        write_json_atomic(cfg.multi_bind_path, {})
    if not cfg.draw_guess_db_path.exists():
        write_json_atomic(cfg.draw_guess_db_path, _default_draw_guess_db())
    if not cfg.hiroba_cooldown_path.exists():
        write_json_atomic(cfg.hiroba_cooldown_path, {})


def read_config(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    ensure_storage_layout(cfg)
    payload = load_json(cfg.config_path, _default_config())
    return payload if isinstance(payload, dict) else _default_config()


def write_config(payload: Dict[str, Any], settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    ensure_storage_layout(cfg)
    write_json_atomic(cfg.config_path, payload)


def userdata_path(user_id: str, settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    return cfg.userdata_dir / f"{str(user_id).strip()}data.json"


def userdata_history_dir(user_id: str, settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    return cfg.userdata_dir / str(user_id).strip()


def read_userdata(user_id: str, settings: Settings | None = None) -> Optional[Dict[str, Any]]:
    path = userdata_path(user_id, settings=settings)
    payload = load_json(path, None)
    return payload if isinstance(payload, dict) else None


def write_userdata_with_history(
    user_id: str,
    payload: Dict[str, Any],
    *,
    source: str = "manual",
    settings: Settings | None = None,
) -> Path:
    cfg = settings or get_settings()
    ensure_storage_layout(cfg)
    normalized_user_id = str(user_id).strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")

    save_path = userdata_path(normalized_user_id, settings=cfg)
    history_dir = userdata_history_dir(normalized_user_id, settings=cfg)
    history_dir.mkdir(parents=True, exist_ok=True)

    previous = read_userdata(normalized_user_id, settings=cfg)
    panel_data = payload.get("profile", {})
    achievement_data = payload.get("achievement", {})
    dojo_data = payload.get("dojo", {})
    songs = payload.get("songs", [])
    merged_payload = {
        **payload,
        "_meta": {
            **(payload.get("_meta") or {}),
            "source": source,
            "synced_at": datetime.now().isoformat(timespec="seconds"),
        },
        "profile": panel_data,
        "achievement": achievement_data,
        "dojo": dojo_data,
        "songs": songs,
    }
    write_json_atomic(save_path, merged_payload)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    delta_snapshot: Dict[str, Any] = {"_meta": {"full": previous is None, "ts": ts, "source": source}}
    if previous is None:
        delta_snapshot.update(
            {
                "profile": panel_data,
                "achievement": achievement_data,
                "dojo": dojo_data,
                "songs": songs,
            }
        )
    else:
        previous_song_map = {
            (song.get("song_no"), song.get("level")): song
            for song in previous.get("songs", []) or []
            if isinstance(song, dict)
        }
        current_song_map = {
            (song.get("song_no"), song.get("level")): song
            for song in songs or []
            if isinstance(song, dict)
        }
        changed_songs = []
        for key, song in current_song_map.items():
            if previous_song_map.get(key) != song:
                changed_songs.append(song)
        removed_keys = [list(key) for key in previous_song_map.keys() if key not in current_song_map]
        if previous.get("profile") != panel_data:
            delta_snapshot["profile"] = panel_data
        if previous.get("achievement") != achievement_data:
            delta_snapshot["achievement"] = achievement_data
        if previous.get("dojo") != dojo_data:
            delta_snapshot["dojo"] = dojo_data
        delta_snapshot["songs"] = changed_songs
        if removed_keys:
            delta_snapshot["songs_removed"] = removed_keys
    history_path = history_dir / f"data_{ts}.json"
    write_json_atomic(history_path, delta_snapshot)
    return save_path


def list_userdata_history(user_id: str, settings: Settings | None = None) -> list[Path]:
    history_dir = userdata_history_dir(user_id, settings=settings)
    if not history_dir.exists():
        return []
    return sorted(history_dir.glob("data_*.json"))


def read_multi_bind_store(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    ensure_storage_layout(cfg)
    payload = load_json(cfg.multi_bind_path, {})
    return payload if isinstance(payload, dict) else {}


def write_multi_bind_store(payload: Dict[str, Any], settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    ensure_storage_layout(cfg)
    write_json_atomic(cfg.multi_bind_path, payload)


def read_draw_guess_db(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    ensure_storage_layout(cfg)
    payload = load_json(cfg.draw_guess_db_path, _default_draw_guess_db())
    return payload if isinstance(payload, dict) else _default_draw_guess_db()


def write_draw_guess_db(payload: Dict[str, Any], settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    ensure_storage_layout(cfg)
    write_json_atomic(cfg.draw_guess_db_path, payload)
