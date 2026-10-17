"""Installed standalone Bot entry; source checkouts are never searched at runtime."""
import os
from pathlib import Path


def create_app():
    import nonebot
    from nonebot.adapters.qq import Adapter as QQAdapter
    from onebot_runtime.adapter import Adapter as OneBotAdapter

    profile = os.environ.get("TAIKO_SONG_PROFILE", "client")
    if profile not in {"center", "client"}:
        raise ValueError("TAIKO_SONG_PROFILE must be center or client")
    runtime = Path(os.environ.get("TAIKO_RUNTIME_ROOT", os.environ.get("TAIKO_BOT_ROOT", "."))).resolve()
    os.environ.setdefault("TAIKO_BOT_ROOT", str(runtime))
    os.environ.setdefault("TAIKO_CENTER_ROOT", str(runtime))
    os.environ.setdefault("TAIKO_OFFLINE_ROOT", str(runtime))
    os.environ.setdefault("DRIVER", "~fastapi+~httpx+~websockets")
    if profile == "center":
        from taiko_bot.runtime.player.center.runtime_env import load_runtime_environment
        load_runtime_environment()
    nonebot.init(
        _env_file=os.environ.get("TAIKO_BOT_ENV_FILE", str(runtime / ".env.prod" if profile == "center" else runtime / ".env")),
        taiko_song_profile=profile,
        taiko_song_public_root=str(runtime),
    )
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotAdapter)
    driver.register_adapter(QQAdapter)
    plugins = [
        "feature_handler", "taiko_bot.runtime.public",
        "taiko_bot.runtime.player.entry", "taiko_bot.runtime.community.community_entry",
        "taiko_bot.runtime.center_startup" if profile == "center" else "taiko_runtime_init",
        "bot_pool_metrics", "nonebot_plugin_method_calls",
    ]
    if profile == "center":
        plugins.append("nonebot_plugin_groupmate_taiko")
    for name in plugins:
        if nonebot.load_plugin(name) is None:
            raise RuntimeError(f"Required Taiko module failed to load: {name}")
    app = nonebot.get_asgi()
    if profile == "client":
        from taiko_bot.local_api import app as local_app
        app.mount("/local-api", local_app)
    return app


def main():
    import nonebot
    create_app()
    nonebot.run()
