import importlib
from runtime_owner import load_community_owner
from test_taiko_runtime import FakeQQGroupEvent, FakeSegment

def test_draw_guess_session_keys_use_official_group_scope():
    taiko = load_community_owner()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-1",
        segments=[FakeSegment("text", {"text": "猜太鼓歌名"})],
    )

    assert taiko._draw_guess_group_session_key(event) == "group_openid_1"
    assert taiko._draw_guess_user_session_key(event) == "group:group_openid_1:user:member_openid_self"
