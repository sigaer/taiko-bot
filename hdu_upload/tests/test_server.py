import time
import unittest
from types import SimpleNamespace

from hdu_upload.server import Settings, choose_part_size, create_app, create_token, normalize_filename, read_token


class FakeBucket:
    def __init__(self):
        self.completed = None

    def object_exists(self, _key):
        return False

    def init_multipart_upload(self, _key, headers=None):
        return SimpleNamespace(upload_id="upload-123")

    def sign_url(self, _method, key, _expires, **kwargs):
        number = kwargs["params"]["partNumber"]
        return f"https://oss.example/{key}?partNumber={number}"

    def complete_multipart_upload(self, key, upload_id, parts):
        self.completed = (key, upload_id, parts)

    def abort_multipart_upload(self, _key, _upload_id):
        return None


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.bucket = FakeBucket()
        self.settings = Settings("https://oss.example", "id", "secret")
        self.client = create_app(self.settings, self.bucket).test_client()

    def test_normalize_filename_rejects_paths(self):
        with self.assertRaises(ValueError):
            normalize_filename("folder/file.mp4")
        self.assertEqual(normalize_filename("  昵称-歌曲.mp4  "), "昵称-歌曲.mp4")

    def test_part_size_stays_below_oss_part_limit(self):
        size = 100 * 1024 * 1024 * 1024
        self.assertLessEqual((size + choose_part_size(size) - 1) // choose_part_size(size), 9500)

    def test_token_rejects_tampering_and_expiry(self):
        secret = b"secret"
        token = create_token(secret, {"expires": int(time.time()) + 10})
        self.assertIn("expires", read_token(secret, token))
        with self.assertRaises(ValueError):
            read_token(secret, token + "x")
        expired = create_token(secret, {"expires": 1})
        with self.assertRaisesRegex(ValueError, "过期"):
            read_token(secret, expired)

    def test_upload_flow_is_fixed_to_video_4(self):
        started = self.client.post(
            "/api/uploads",
            json={"filename": "player-song.mp4", "size": 20 * 1024 * 1024, "contentType": "video/mp4"},
        )
        self.assertEqual(started.status_code, 200)
        session = started.get_json()
        self.assertEqual(session["partCount"], 2)

        signed = self.client.post(
            "/api/uploads/parts",
            json={"token": session["token"], "partNumbers": [1, 2]},
        )
        self.assertEqual(signed.status_code, 200)
        self.assertIn("video_4/player-song.mp4", signed.get_json()["urls"]["1"])


if __name__ == "__main__":
    unittest.main()
