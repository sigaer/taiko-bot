#!/usr/bin/env python3
import argparse
import json
import logging
import os
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from taiko_bot.services.credential_control import ControlError, MAX_BODY, authorized_update, require_bearer

from taiko_bot.runtime.player.center.public_score_token import (
    PublicScoreTokenError,
    fetch_latest_userdata_by_token,
)

from taiko_bot.runtime.paths import root
BASE_DIR = root()
SONG_DATA_PATH = BASE_DIR / "songs" / "song_data.json"
ALIAS_DATA_PATH = BASE_DIR / "songs" / "song_alias.json"
CONFIG_PATH = BASE_DIR / "config.json"
API_PATH = "/api/song_data"
TOKEN_API_PATH = "/api/token"
PUBLIC_SCORE_API_PATH = "/api/public-score/by-token"
MAX_PUBLIC_SCORE_BODY_BYTES = 16 * 1024


def load_song_data() -> Any:
    with SONG_DATA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_alias_data() -> Any:
    with ALIAS_DATA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_song_id(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def build_alias_map(alias_data: Any) -> Dict[int, List[str]]:
    if not isinstance(alias_data, list):
        raise ValueError("alias_data_format")
    alias_map: Dict[int, List[str]] = {}
    for item in alias_data:
        if not isinstance(item, dict):
            continue
        song_id = normalize_song_id(item.get("id"))
        if song_id is None:
            continue
        aliases = item.get("aliases", [])
        if not isinstance(aliases, list):
            continue
        alias_map[song_id] = [alias for alias in aliases if isinstance(alias, str)]
    return alias_map


def attach_aliases(song_data: Any, alias_map: Dict[int, List[str]]) -> Any:
    if not isinstance(song_data, list):
        raise ValueError("song_data_format")
    for song in song_data:
        if not isinstance(song, dict):
            continue
        song_id = normalize_song_id(song.get("id"))
        song["aliases"] = alias_map.get(song_id, [])
    return song_data


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        return data
    raise ValueError("config_json_format")


def update_cookie(token: str) -> None:
    # Called only inside the shared control-plane process lock after live proof.
    if CONFIG_PATH.is_symlink() or not CONFIG_PATH.is_file():
        raise ValueError("credential_storage_unavailable")
    data = load_config()
    data["cookie"] = token
    descriptor, temporary = tempfile.mkstemp(prefix=".credential-", dir=CONFIG_PATH.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=4)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, CONFIG_PATH)
        directory = os.open(CONFIG_PATH.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SongDataHandler(BaseHTTPRequestHandler):
    server_version = "SongDataHTTP/1.0"
    _SUPPRESSED_ERRORS = (
        "Bad HTTP/0.9 request type",
        "Bad request version",
    )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != API_PATH:
            self.send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not_found", "message": "Unknown endpoint."},
            )
            return

        try:
            data = load_song_data()
        except FileNotFoundError:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "file_missing",
                    "message": f"Missing file: {SONG_DATA_PATH}",
                },
            )
            return
        except json.JSONDecodeError:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "invalid_json",
                    "message": "song_data.json is not valid JSON.",
                },
            )
            return
        except Exception:
            logging.exception("Unhandled error while loading song data")
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "internal_error",
                    "message": "Unexpected server error.",
                },
            )
            return

        try:
            alias_data = load_alias_data()
            alias_map = build_alias_map(alias_data)
            merged_data = attach_aliases(data, alias_map)
        except FileNotFoundError:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "alias_file_missing",
                    "message": f"Missing file: {ALIAS_DATA_PATH}",
                },
            )
        except json.JSONDecodeError:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "alias_invalid_json",
                    "message": "song_alias.json is not valid JSON.",
                },
            )
        except ValueError as exc:
            error_code = "alias_data_invalid"
            message = str(exc)
            if message == "song_data_format":
                error_code = "song_data_invalid"
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": error_code,
                    "message": message,
                },
            )
        except Exception:
            logging.exception("Unhandled error while merging alias data")
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": "internal_error",
                    "message": "Unexpected server error.",
                },
            )
        else:
            self.send_json(HTTPStatus.OK, merged_data)

    def do_HEAD(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_OPTIONS(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != PUBLIC_SCORE_API_PATH:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Allow", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            return

        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == PUBLIC_SCORE_API_PATH:
            self.handle_public_score_post()
            return

        if parsed.path != TOKEN_API_PATH:
            self.send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not_found", "message": "Unknown endpoint."},
            )
            return

        self.close_connection = True
        self.connection.settimeout(5)
        try:
            if parsed.query or parsed.fragment:
                raise ControlError(400)
            require_bearer(self.headers.get("Authorization"))
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ControlError(400) from None
            if length <= 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                raise ControlError(400)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ControlError(400)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ControlError(400)
            authorized_update(self.headers.get("Authorization"), raw, "taiko-token", update_cookie)
        except ControlError as error:
            self.send_json(error.status, {"error": "credential_update_denied"})
        except Exception:
            self.send_json(503, {"error": "credential_update_unavailable"})
        else:
            self.send_json(HTTPStatus.OK, {"status": "ok"})

    def handle_public_score_post(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_body", "message": "Missing request body."},
                cors=True,
            )
            return

        if length > MAX_PUBLIC_SCORE_BODY_BYTES:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": "payload_too_large", "message": "Request body is too large."}, cors=True)
            return

        try:
            self.connection.settimeout(15)
            raw = self.rfile.read(length)
        except (TimeoutError, OSError):
            self.send_json(HTTPStatus.REQUEST_TIMEOUT,
                {"error": "request_timeout", "message": "Request body timed out."}, cors=True)
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_json", "message": "Request body is not valid JSON."},
                cors=True,
            )
            return

        if not isinstance(payload, dict):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_payload", "message": "JSON body must be an object."},
                cors=True,
            )
            return

        token = payload.get("token")
        if not isinstance(token, str) or not token.strip():
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_token", "message": "Missing token field."},
                cors=True,
            )
            return

        try:
            result = fetch_latest_userdata_by_token(token.strip())
        except PublicScoreTokenError as error:
            self.send_json(
                HTTPStatus(error.status_code),
                {"error": error.error, "message": error.message},
                cors=True,
            )
        except Exception:
            logging.exception("Unhandled error while loading public score payload")
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error", "message": "Unexpected server error."},
                cors=True,
            )
        else:
            self.send_json(HTTPStatus.OK, result, cors=True)

    def do_PUT(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_DELETE(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def log_message(self, fmt: str, *args: Any) -> None:
        if urlparse(getattr(self, "path", "")).path == TOKEN_API_PATH:
            logging.info("Credential control request completed")
            return
        message = fmt % args
        if self._should_suppress_log(message):
            return
        logging.info("%s - %s", self.address_string(), message)

    @classmethod
    def _should_suppress_log(cls, message: str) -> bool:
        if any(marker in message for marker in cls._SUPPRESSED_ERRORS):
            return True
        # Drop log lines with control characters (usually TLS handshakes on HTTP).
        return any(
            (ord(ch) < 32 and ch not in "\t\n\r") or ord(ch) == 127 for ch in message
        )

    def send_json(self, status: HTTPStatus, payload: Any, cors: bool = False) -> None:
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if urlparse(self.path).path == TOKEN_API_PATH:
                self.send_header("Cache-Control", "private, no-store")
            if cors:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            logging.warning("Client disconnected before response was sent")
        except Exception:
            logging.exception("Failed to send response")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simple API server that returns songs/song_data.json."
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host.")
    parser.add_argument("--port", type=int, default=9999, help="Bind port.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    server_address = (args.host, args.port)
    httpd = ThreadingHTTPServer(server_address, SongDataHandler)
    logging.info(
        "Serving %s at http://%s:%s%s", SONG_DATA_PATH, args.host, args.port, API_PATH
    )

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
