from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .settings import Settings, ensure_runtime_dirs, get_settings


def _default_draw_guess_db() -> Dict[str, Any]:
    return {"next_id": 1, "records": [], "user_guess_stats": {}}


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
        cfg.root_dir / "data": cfg.runtime_data_dir,
        cfg.root_dir / "logs": cfg.logs_dir,
        cfg.root_dir / "output": cfg.output_dir,
        cfg.root_dir / "secrets": cfg.secrets_dir,
        cfg.root_dir / "userdata": cfg.userdata_dir,
    }
    for link_path, target_path in compatibility_links.items():
        if link_path.is_symlink():
            try:
                if link_path.resolve() == target_path.resolve():
                    continue
            except OSError:
                pass
            try:
                link_path.unlink()
            except OSError:
                continue
        elif link_path.exists():
            continue
        try:
            link_path.symlink_to(target_path)
        except OSError:
            # Filesystems without symlink support fall back to the storage path directly.
            pass
    if not cfg.multi_bind_path.exists():
        write_json_atomic(cfg.multi_bind_path, {})
    if not cfg.draw_guess_db_path.exists():
        write_json_atomic(cfg.draw_guess_db_path, _default_draw_guess_db())
    if not cfg.hiroba_cooldown_path.exists():
        write_json_atomic(cfg.hiroba_cooldown_path, {})

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
