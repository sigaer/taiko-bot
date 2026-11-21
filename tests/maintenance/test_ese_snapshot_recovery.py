import subprocess
from taiko_bot.offline import ese_audio_sync


def test_unrelated_managed_mirror_tracks_snapshot_and_keeps_old_revision(tmp_path, monkeypatch):
    def git(path, *args):
        return subprocess.run(["git", "-C", str(path), *args], check=True, text=True, capture_output=True).stdout.strip()

    old, upstream = tmp_path / "mirror", tmp_path / "upstream"
    for path, content in [(old, "old"), (upstream, "new")]:
        path.mkdir()
        git(path, "init", "-b", "master")
        git(path, "config", "user.email", "qa@example.invalid")
        git(path, "config", "user.name", "QA")
        (path / "chart.tja").write_text(content)
        git(path, "add", "chart.tja")
        git(path, "commit", "-m", content)
    git(old, "remote", "add", "origin", str(upstream))
    previous = git(old, "rev-parse", "HEAD")
    monkeypatch.setattr(ese_audio_sync, "ESE_REPO_URL_ALIASES", (str(upstream),))
    result = ese_audio_sync._update_managed_snapshot(old)
    assert git(old, "rev-parse", "HEAD") == git(upstream, "rev-parse", "HEAD")
    assert (old / "chart.tja").read_text() == "new"
    assert git(old, "rev-parse", result["backup_ref"]) == previous
    assert git(old, "show", result["backup_ref"] + ":chart.tja") == "old"
    assert ese_audio_sync._update_managed_snapshot(old) is None


