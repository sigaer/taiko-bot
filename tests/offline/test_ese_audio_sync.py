from __future__ import annotations

import subprocess
from pathlib import Path

from taiko_bot.offline import branch_audio_manifest
from taiko_bot.offline import ese_audio_sync


def test_run_repo_git_recovers_from_stale_index_lock(tmp_path: Path, monkeypatch):
    repo_path = tmp_path / "ESE_autosync"
    git_dir = repo_path / ".git"
    git_dir.mkdir(parents=True)
    lock_path = git_dir / "index.lock"
    lock_path.write_text("", encoding="utf-8")

    calls = []

    def fake_run(cmd, cwd=None, check=True, timeout=None):
        calls.append((tuple(cmd), cwd, check, timeout))
        if len(calls) == 1:
            raise RuntimeError(
                "command failed: git sparse-checkout init --cone\n"
                "stderr:\n"
                f"fatal: Unable to create '{lock_path}': File exists.\n"
                "Another git process seems to be running."
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(ese_audio_sync, "_run", fake_run)
    monkeypatch.setattr(
        ese_audio_sync,
        "_find_git_processes_for_repo",
        lambda repo: [],
    )

    result = ese_audio_sync._run_repo_git(["git", "status", "--short"], repo_path)

    assert result.stdout == "ok\n"
    assert len(calls) == 2
    assert not lock_path.exists()


def test_ensure_sparse_checkout_skips_reconfigure_when_already_matches(monkeypatch):
    commands = []

    def fake_run_repo_git(cmd, repo_path, check=True, timeout=None):
        commands.append(tuple(cmd))
        if cmd[:4] == ["git", "config", "--bool", "core.sparseCheckout"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
        if cmd[:3] == ["git", "sparse-checkout", "list"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="\n".join(ese_audio_sync.ESE_CATEGORY_DIRS) + "\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(ese_audio_sync, "_run_repo_git", fake_run_repo_git)

    changed = ese_audio_sync._ensure_sparse_checkout(Path("/tmp/ese"))

    assert changed is False
    assert commands == [
        ("git", "config", "--bool", "core.sparseCheckout"),
        ("git", "sparse-checkout", "list"),
    ]


def test_clone_ese_repo_uses_official_sparse_clone(tmp_path: Path, monkeypatch):
    commands = []
    repo_path = tmp_path / "ESE_autosync"

    def fake_run(cmd, cwd=None, check=True, timeout=None):
        commands.append((tuple(cmd), cwd))
        if cmd[:2] == ["git", "clone"]:
            repo_path.mkdir(parents=True, exist_ok=True)
            (repo_path / ".git").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ese_audio_sync, "_run", fake_run)
    monkeypatch.setattr(
        ese_audio_sync,
        "_run_repo_git",
        lambda cmd, repo_path, check=True, timeout=None: subprocess.CompletedProcess(
            cmd,
            0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        ese_audio_sync,
        "_ensure_sparse_checkout",
        lambda repo_path: False,
    )

    clone_info = ese_audio_sync._clone_ese_repo(repo_path)

    assert clone_info == {
        "clone_source": ese_audio_sync.ESE_REPO_URL,
        "seeded_from_local_repo": False,
    }
    assert commands[0][0] == (
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        ese_audio_sync.ESE_BRANCH,
        "--filter=blob:none",
        "--sparse",
        ese_audio_sync.ESE_REPO_URL,
        str(repo_path),
    )


def _write_branch_tja(
    path: Path,
    branch_start: str,
    normal_notes: str,
    expert_notes: str,
    master_notes: str,
) -> None:
    path.write_text(
        "\n".join(
            [
                "TITLE:Branch test",
                "COURSE:Oni",
                "LEVEL:9",
                "#START",
                "1000,",
                branch_start,
                "#N",
                normal_notes,
                "#E",
                expert_notes,
                "#M",
                master_notes,
                "#BRANCHEND",
                "#END",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_branch_manifest_keeps_only_reachable_tetoris_path(tmp_path: Path):
    tja_path = tmp_path / "tetoris.tja"
    _write_branch_tja(
        tja_path,
        "#BRANCHSTART p,-2,-1",
        "1111,",
        "1111,",
        "1111,",
    )

    tracks = branch_audio_manifest.analyze_tja_branch_variants(tja_path)

    assert [group["labels"] for group in tracks["ONI"]] == [["达人"]]


def test_branch_manifest_merges_equal_reachable_paths(tmp_path: Path):
    tja_path = tmp_path / "two-path.tja"
    _write_branch_tja(
        tja_path,
        "#BRANCHSTART p,80,80",
        "1111,",
        "2222,",
        "1111,",
    )

    tracks = branch_audio_manifest.analyze_tja_branch_variants(tja_path)

    assert [group["labels"] for group in tracks["ONI"]] == [
        ["普通", "达人"]
    ]


def test_branch_manifest_requires_playable_drum_and_mix_assets(tmp_path: Path):
    tja_path = tmp_path / "assets.tja"
    _write_branch_tja(
        tja_path,
        "#BRANCHSTART p,80,80",
        "1111,",
        "2222,",
        "3333,",
    )
    candidate = {
        "song": {"id": 42},
        "tja_path": tja_path,
    }
    drum_objects = {
        "42_ONI_普通.mp3",
        "42_ONI_达人.mp3",
    }
    mix_objects = {
        "42_ONI_达人.mp3",
    }

    manifest = branch_audio_manifest.build_branch_audio_manifest(
        [candidate],
        drum_objects,
        mix_objects,
        source_revision="test",
    )

    assert [
        {
            "label": item["label"],
            "aliases": item["aliases"],
            "available": item["available"],
        }
        for item in manifest["songs"]["42"]["ONI"]
    ] == [
        {"label": "普通", "aliases": [], "available": False},
        {"label": "达人", "aliases": [], "available": True},
    ]
    assert manifest["stats"]["missingAssetGroupCount"] == 1
    assert manifest["stats"]["missingVariantCount"] == 1


def test_branch_manifest_keeps_course_across_double_and_single_charts(
    tmp_path: Path,
):
    tja_path = tmp_path / "double-then-single.tja"
    tja_path.write_text(
        "\n".join(
            [
                "TITLE:Double then single",
                "COURSE:Oni",
                "STYLE:Double",
                "#START P1",
                "1000,",
                "#END",
                "#START P2",
                "2000,",
                "#END",
                "STYLE:Single",
                "#START",
                "#BRANCHSTART p,50,80",
                "#N",
                "1000,",
                "#E",
                "2000,",
                "#M",
                "3000,",
                "#BRANCHEND",
                "#END",
                "",
            ]
        ),
        encoding="utf-8",
    )

    tracks = branch_audio_manifest.analyze_tja_branch_variants(tja_path)

    assert [variant["labels"] for variant in tracks["ONI"]] == [
        ["普通"],
        ["玄人"],
        ["达人"],
    ]


def test_metadata_matcher_resolves_same_title_by_chart_data(tmp_path: Path):
    short_path = tmp_path / "same-title-old.tja"
    current_path = tmp_path / "same-title-current.tja"
    for path, notes in (
        (short_path, "1111,"),
        (current_path, "11111111,"),
    ):
        path.write_text(
            "\n".join(
                [
                    "TITLEJA:同名歌曲",
                    "TITLE:Same title",
                    "BPM:120",
                    "COURSE:Oni",
                    "LEVEL:7",
                    "#START",
                    notes,
                    "#END",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    records = [
        ese_audio_sync._build_tja_record(short_path),
        ese_audio_sync._build_tja_record(current_path),
    ]
    matcher = ese_audio_sync._build_metadata_matcher(tmp_path, records)
    song = {
        "id": 42,
        "song_name_jp": "同名歌曲",
        "song_name": "Same title",
        "bpm": "120",
        "level_4": 7,
        "max_combo": ["-", "-", "-", 8, "-"],
        "shelf_status": 0,
    }

    matched, skipped = ese_audio_sync._match_songs_with_metadata(
        [song],
        tmp_path,
        matcher,
    )

    assert skipped == []
    selected = next(iter(matched[42].values()))
    assert selected["tja_path"] == current_path
    assert selected["match_strategy"] == "metadata"
