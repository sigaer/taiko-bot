from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PUBLIC_DATA_FILES = {
    "song_data": "song_data.json",
    "song_alias": "song_alias.json",
    "rating_structured_with_ids": "rating_structured_with_ids.json",
    "region_map": "region_map.json",
    "music_donda_list": "music_donda_list.json",
    "song_difficulty": "song_difficulty.json",
    "song_score": "song_score.json",
    "song_data_with_roll": "song_data_with_roll.json",
    "taiko_goku_onis": "taiko_goku_onis.json",
    "grade_dojo_nijiiro_2025_simple": "grade_dojo_nijiiro_2025_simple.json",
    "grade_dojo_nijiiro_history_simple": "grade_dojo_nijiiro_history_simple.json",
    "analyze_result_filtered": "analyze_result_filtered.json",
    "tja_note_counts": "tja_note_counts.json",
    "city": "city.json",
    "twso": "twso_data.json",
}


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    storage_dir: Path
    songs_dir: Path
    assets_dir: Path
    config_path: Path
    userdata_dir: Path
    runtime_data_dir: Path
    logs_dir: Path
    output_dir: Path
    secrets_dir: Path
    sqlite_path: Path
    multi_bind_path: Path
    draw_guess_dir: Path
    draw_guess_db_path: Path
    alias_log_path: Path
    hiroba_token_dir: Path
    hiroba_cooldown_path: Path
    qq_markdown_cache_dir: Path
    public_data_base_url: str
    local_data_api_host: str
    local_data_api_port: int
    local_data_api_base_url: str
    qq_markdown_image_base_url: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    root_dir = Path(
        os.getenv("TAIKO_BOT_ROOT", Path(__file__).resolve().parents[1])
    ).resolve()
    storage_dir = Path(
        os.getenv("TAIKO_STORAGE_DIR", root_dir / "storage")
    ).resolve()
    songs_dir = Path(os.getenv("TAIKO_SONGS_DIR", root_dir / "songs")).resolve()
    assets_dir = Path(os.getenv("TAIKO_ASSETS_DIR", root_dir / "assets")).resolve()
    runtime_data_dir = storage_dir / "data"
    logs_dir = Path(os.getenv("TAIKO_LOGS_DIR", storage_dir / "logs")).resolve()
    output_dir = Path(
        os.getenv("TAIKO_OUTPUT_DIR", storage_dir / "output")
    ).resolve()
    secrets_dir = Path(
        os.getenv("TAIKO_SECRETS_DIR", storage_dir / "secrets")
    ).resolve()
    local_data_api_host = os.getenv("TAIKO_LOCAL_DATA_API_HOST", "127.0.0.1")
    local_data_api_port = int(os.getenv("TAIKO_LOCAL_DATA_API_PORT", "37565") or 37565)
    local_data_api_base_url = os.getenv(
        "TAIKO_LOCAL_DATA_API_BASE_URL",
        f"http://{local_data_api_host}:{local_data_api_port}",
    ).rstrip("/")
    qq_markdown_cache_dir = Path(
        os.getenv(
            "QQ_MARKDOWN_IMAGE_CACHE_DIR",
            output_dir / "qq_markdown_cache",
        )
    ).resolve()
    return Settings(
        root_dir=root_dir,
        storage_dir=storage_dir,
        songs_dir=songs_dir,
        assets_dir=assets_dir,
        config_path=Path(
            os.getenv("TAIKO_CONFIG_PATH", storage_dir / "config" / "config.json")
        ).resolve(),
        userdata_dir=Path(
            os.getenv("TAIKO_USERDATA_DIR", storage_dir / "userdata")
        ).resolve(),
        runtime_data_dir=runtime_data_dir.resolve(),
        logs_dir=logs_dir,
        output_dir=output_dir,
        secrets_dir=secrets_dir,
        sqlite_path=Path(
            os.getenv("TAIKO_SQLITE_PATH", runtime_data_dir / "taiko.sqlite3")
        ).resolve(),
        multi_bind_path=Path(
            os.getenv("TAIKO_MULTI_BIND_PATH", runtime_data_dir / "taiko_multi_bind.json")
        ).resolve(),
        draw_guess_dir=Path(
            os.getenv("TAIKO_DRAW_GUESS_DIR", runtime_data_dir / "draw_guess")
        ).resolve(),
        draw_guess_db_path=Path(
            os.getenv(
                "TAIKO_DRAW_GUESS_DB_PATH",
                runtime_data_dir / "draw_guess" / "records.json",
            )
        ).resolve(),
        alias_log_path=Path(
            os.getenv("TAIKO_ALIAS_LOG_PATH", logs_dir / "alias_action_log.json")
        ).resolve(),
        hiroba_token_dir=Path(
            os.getenv("TAIKO_HIROBA_TOKEN_DIR", secrets_dir / "hiroba_tokens")
        ).resolve(),
        hiroba_cooldown_path=Path(
            os.getenv(
                "TAIKO_HIROBA_COOLDOWN_PATH",
                runtime_data_dir / "hiroba_sync_cooldown.json",
            )
        ).resolve(),
        qq_markdown_cache_dir=qq_markdown_cache_dir,
        public_data_base_url=os.getenv(
            "TAIKO_PUBLIC_DATA_BASE_URL", "https://viewer.sakura-bot.cn/api/taiko"
        ).rstrip("/"),
        local_data_api_host=local_data_api_host,
        local_data_api_port=local_data_api_port,
        local_data_api_base_url=local_data_api_base_url,
        qq_markdown_image_base_url=os.getenv(
            "QQ_MARKDOWN_IMAGE_BASE_URL",
            "https://viewer.sakura-bot.cn/qqbot-cache/taiko",
        ).rstrip("/"),
    )


def ensure_runtime_dirs(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    for path in (
        cfg.storage_dir,
        cfg.songs_dir,
        cfg.assets_dir,
        cfg.config_path.parent,
        cfg.userdata_dir,
        cfg.runtime_data_dir,
        cfg.logs_dir,
        cfg.output_dir,
        cfg.secrets_dir,
        cfg.hiroba_token_dir,
        cfg.draw_guess_dir,
        cfg.qq_markdown_cache_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
