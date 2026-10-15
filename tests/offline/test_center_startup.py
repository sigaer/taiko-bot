import sqlite3
from pathlib import Path
from taiko_bot.runtime.center_startup_migration import migrate_feature_switch_db, migrate_multi_bind_payload

def test_migrate_multi_bind_payload_prefixes_and_merges():
    payload = {
        "12345": {"ids": ["111", "222"], "current_index": 1},
        "onebot_v11:12345": {"ids": ["222", "333"], "current_index": 0},
        "qq_official:openid_1": {"ids": ["999"], "current_index": 0},
    }

    migrated, stats = migrate_multi_bind_payload(payload)

    assert migrated["onebot_v11:12345"]["ids"] == ["222", "333", "111"]
    assert migrated["onebot_v11:12345"]["current_index"] == 0
    assert migrated["onebot_v11:12345"]["current_slot"] == 1
    assert migrated["qq_official:openid_1"]["ids"] == ["999"]
    assert migrated["qq_official:openid_1"]["current_slot"] == 1
    assert stats["migrated"] == 1
    assert stats["merged"] == 1

def test_migrate_feature_switch_db_prefixes_group_ids(tmp_path: Path):
    db_path = tmp_path / "switch.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE feature_switch (
          group_id   TEXT NOT NULL,
          feature    TEXT NOT NULL,
          enabled    INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY(group_id, feature)
        )
        """
    )
    conn.execute(
        "INSERT INTO feature_switch (group_id, feature, enabled, updated_at) VALUES (?, ?, ?, ?)",
        ("12345", "taiko", 1, 10),
    )
    conn.execute(
        "INSERT INTO feature_switch (group_id, feature, enabled, updated_at) VALUES (?, ?, ?, ?)",
        ("onebot_v11:12345", "tsearch", 0, 20),
    )
    conn.execute(
        "INSERT INTO feature_switch (group_id, feature, enabled, updated_at) VALUES (?, ?, ?, ?)",
        ("perf_test_group", "taiko", 1, 30),
    )
    conn.commit()
    conn.close()

    stats = migrate_feature_switch_db(db_path)

    assert stats == {"migrated": 1, "merged": 0}
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT group_id, feature, enabled, updated_at FROM feature_switch ORDER BY group_id, feature"
    ).fetchall()
    conn.close()
    assert rows == [
        ("onebot_v11:12345", "taiko", 1, 10),
        ("onebot_v11:12345", "tsearch", 0, 20),
        ("perf_test_group", "taiko", 1, 30),
    ]


def test_startup_hooks_preserve_migration_cleanup_and_failure(monkeypatch,tmp_path):
    import asyncio, importlib, sys
    from types import SimpleNamespace
    import nonebot
    from taiko_bot.offline import memory
    calls=[]
    class Driver:
        config=SimpleNamespace(dict=lambda:{'feature_switch_data_dir':str(tmp_path)})
        def on_startup(self,fn):return fn
        def on_shutdown(self,fn):return fn
    monkeypatch.setattr(nonebot,'get_driver',lambda:Driver())
    sys.modules.pop('taiko_bot.runtime.center_startup',None)
    module=importlib.import_module('taiko_bot.runtime.center_startup')
    monkeypatch.setattr(memory,'start_telemetry',lambda name:calls.append(('telemetry',name)))
    monkeypatch.setattr(module,'migrate_feature_switch_db',lambda path:calls.append(('migration',path.name)))
    monkeypatch.setattr(module,'ensure_hiroba_credentials_table',lambda:calls.append(('credentials',)))
    monkeypatch.setattr(module,'start_cleanup_task',lambda:calls.append(('cleanup',)))
    async def stop():calls.append(('stop',))
    monkeypatch.setattr(module,'stop_cleanup_task',stop)
    asyncio.run(module._run_taiko_startup_migrations())
    asyncio.run(module._shutdown_qq_markdown_cleanup_task())
    assert calls==[('telemetry','taikobot'),('migration','switch.db'),('credentials',),('cleanup',),('stop',)]
    def unavailable():raise RuntimeError('synthetic DB unavailable')
    monkeypatch.setattr(module,'ensure_hiroba_credentials_table',unavailable)
    calls.clear();asyncio.run(module._run_taiko_startup_migrations())
    assert calls[-1]==('cleanup',)
