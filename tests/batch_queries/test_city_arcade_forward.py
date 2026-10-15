from __future__ import annotations

from taiko_bot.runtime.player.center.query_cluster import _build_city_arcade_forward_messages
from taiko_bot.runtime.player.center import arcade_map as am
from tests.test_taiko_runtime import FakeOneBotGroupEvent, FakeSegment


class FakeBot:
    self_id = 10000


def _build_sample_query_result() -> am.CityShopQueryResult:
    return am.CityShopQueryResult(
        city=am.CityEntry(
            city_code="210300000000",
            name="鞍山市",
            province_code="210000000000",
        ),
        total_arcade_records=2,
        returned_arcade_records=2,
        pagination_broken=False,
        shops=(
            am.CityShopEntry(
                shop_id=5651,
                name="MELAND（鞍山万象汇店）",
                address="辽宁省鞍山市铁东区站前街道华润万象汇三楼反斗乐园",
                transport="鞍山火车站旁边",
                longitude="122.994768",
                latitude="41.108647",
                quantity=1,
                coin=9,
                version="国服",
                open_hours="09:00-20:00",
                machine_comment="机况良好，机台声音略小。",
                shop_comment="",
            ),
            am.CityShopEntry(
                shop_id=9999,
                name="示例店铺",
                address="示例地址",
                transport="",
                longitude="",
                latitude="",
                quantity=2,
                coin=6,
                version="2026春",
                open_hours="10:00-22:00",
                machine_comment="",
                shop_comment="店铺备注",
            ),
        ),
    )


def _node_content_text(node) -> str:
    content = node.data.get("content")
    if isinstance(content, str):
        return content
    return str(content)


def test_build_city_arcade_forward_messages_uses_json_for_shops_with_coordinates():
    bot = FakeBot()
    event = FakeOneBotGroupEvent(
        user_id="12345",
        group_id="67890",
        message_id="1001",
        segments=[FakeSegment("text", {"text": "鞍山哪有鼓"})],
    )
    result = _build_sample_query_result()

    nodes = _build_city_arcade_forward_messages(bot, event, result)

    assert len(nodes) == 3
    assert nodes[0].data["nickname"] == "太鼓地图"
    assert "以下为分店铺地图卡片。" in _node_content_text(nodes[0])

    map_node = nodes[1]
    assert map_node.type == "node"
    assert "MELAND（鞍山万象汇店）" in map_node.data["nickname"]
    content = map_node.data["content"]
    if hasattr(content, "type"):
        json_segment = content
    else:
        json_segments = [segment for segment in content if segment.type == "json"]
        assert len(json_segments) == 1
        json_segment = json_segments[0]
    assert json_segment.type == "json"
    assert '"app":"com.tencent.map"' in json_segment.data["data"]

    text_node = nodes[2]
    assert "示例店铺" in text_node.data["nickname"]
    assert "示例地址" in _node_content_text(text_node)
    assert "店铺备注" in _node_content_text(text_node)
