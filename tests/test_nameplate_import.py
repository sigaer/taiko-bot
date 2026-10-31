from io import BytesIO
import json
from pathlib import Path
import subprocess

from PIL import Image
import pytest

from taiko_bot.offline.nameplate_import import MODULE_MARKER, parse_nameplate_assets, validate_png


def service(rows):
    return MODULE_MARKER + " var o=" + json.dumps(rows) + ';},"./next"'


def test_shared_official_images_keep_game_ids_and_dan_variants():
    base = "https://taiko-file.gzheyoukeji.com/tk/dev/material/title/"
    rows = [{"id": plate_id, "icon": base + "shared.png", "dan_icon": base + "shared_dan.png"}
            for plate_id in (100, 101, 102)]
    assets = parse_nameplate_assets(service(rows))
    assert set(assets) == {f"{prefix}{plate_id}.png" for plate_id in (100, 101, 102)
                           for prefix in ("name_plate_", "name_plate_dani_")}
    assert assets["name_plate_101.png"] == assets["name_plate_100.png"]


@pytest.mark.parametrize("rows", [
    [{"id": "../escape", "icon": "https://bad.example/a", "dan_icon": ""}],
    [{"id": 1, "icon": "https://bad.example/a", "dan_icon": ""}],
    [{"id": 1, "icon": "https://taiko-file.gzheyoukeji.com/a", "dan_icon": "https://taiko-file.gzheyoukeji.com/b"}] * 2,
])
def test_bad_mapping_rejected(rows):
    with pytest.raises(ValueError):
        parse_nameplate_assets(service(rows))


def test_valid_png_and_invalid_downloads():
    stream = BytesIO()
    Image.new("RGBA", (556, 127)).save(stream, format="PNG")
    assert validate_png(stream.getvalue()) == (556, 127)
    for raw in (b"not a png", b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024)):
        with pytest.raises(ValueError):
            validate_png(raw)


def test_nameplate_scope_updates_plate_and_total_archives_only(tmp_path):
    import os
    import zipfile
    source = tmp_path / "source"
    output = tmp_path / "archives"
    for name in ("fonts", "templates", "icons", "cover", "dress", "name_plate", "name_plate_dani", "fumens"):
        folder = source / "assets" / name
        folder.mkdir(parents=True)
        (folder / "fixture.txt").write_text(name)
    output.mkdir()
    untouched = output / "taiko-bot-dress-assets.zip"
    untouched.write_bytes(b"unchanged")
    script = Path(__file__).resolve().parents[1] / "scripts/build_open_resource_archives.sh"
    subprocess.run(["bash", str(script), "nameplate"], env={**os.environ,
                   "TAIKO_SOURCE_ROOT": str(source), "TAIKO_OPEN_RESOURCE_DIR": str(output)},
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert untouched.read_bytes() == b"unchanged"
    assert {path.name for path in output.glob("*.zip")} == {
        "taiko-bot-dress-assets.zip", "taiko-bot-nameplate-assets.zip", "taiko-bot-assets.zip"}
    with zipfile.ZipFile(output / "taiko-bot-nameplate-assets.zip") as archive:
        assert "name_plate/fixture.txt" in archive.namelist()
        assert "name_plate_dani/fixture.txt" in archive.namelist()
        assert "dress/fixture.txt" not in archive.namelist()
    with zipfile.ZipFile(output / "taiko-bot-assets.zip") as archive:
        assert "name_plate/fixture.txt" in archive.namelist()
        assert "dress/fixture.txt" in archive.namelist()
