"""Bounded command regression runner; never opens production private inputs."""
import argparse
import os
from pathlib import Path
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--fixture", type=Path)
parser.add_argument("--profile", choices=("center", "client"), default="center")
parser.add_argument("--load-player", action="store_true")
parser.add_argument("--tests", nargs="+", required=True)
args = parser.parse_args()
assert os.environ.get("QA_RUN_ID"), "Use the bounded QA runner"
tempfile.tempdir = "/var/tmp"
sys.dont_write_bytecode = True
sys.path.insert(0, str(args.source))
if args.profile == "client":
    sys.path.insert(0, "/var/tmp/taiko-b30-performance/core-client")
if args.fixture:
    os.environ.update(TAIKO_RUNTIME_ENV_FILE=str(args.fixture/"absent-command.env"),
        FEATURE_SWITCH_DATA_DIR="/var/tmp/taiko-command-feature-fixture",
        BOT_GROUP_WHITELIST_PATH="/var/tmp/taiko-command-whitelist-fixture.json")
    if args.load_player:
        os.chdir(args.fixture)
        os.environ.update(TAIKO_RUNTIME_ROOT=str(args.fixture), TAIKO_BOT_ROOT=str(args.fixture),
            TAIKO_CENTER_ROOT=str(args.fixture), TAIKO_OFFLINE_ROOT=str(args.fixture),
            TAIKO_USERDATA_DIR=str(args.fixture/"userdata"),
            MPLBACKEND="Agg", MPLCONFIGDIR=str(args.fixture/"mpl"))
        def guard(event, values):
            if event in ("socket.connect", "socket.getaddrinfo", "sqlite3.connect"):
                raise AssertionError("Command checks external IO prohibited")
            if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
                path = os.fsdecode(values[0])
                if path.startswith(("/home/sigaer/taiko/", "/etc/taiko", "/home/sigaer/config/")):
                    raise AssertionError("Command checks production input prohibited")
        sys.addaudithook(guard)
        import nonebot
        nonebot.init(driver="~fastapi", log_level="CRITICAL", taiko_song_profile=args.profile,
            taiko_song_public_root=str(args.fixture))
        nonebot.logger.add(sys.stderr, level="ERROR")
        assert nonebot.load_plugin("taiko_bot.runtime.public")
        assert nonebot.load_plugin("taiko_bot.runtime.player.entry")
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from benchmark import initialize
        initialize(args)
sys.path.append("/usr/lib/python3.11/site-packages")
# Keep pytest's repository conftest from shadowing an installed candidate.
repository = str(Path(__file__).resolve().parents[2])
if repository not in sys.path:
    sys.path.append(repository)
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
import pytest
with tempfile.TemporaryDirectory(prefix="taiko-command-checks-", dir="/var/tmp") as work:
    result = pytest.main(["-q", "--tb=short", "--basetemp", work+"/pytest",
        "-o", "cache_dir="+work+"/cache", *args.tests])
raise SystemExit(result)
