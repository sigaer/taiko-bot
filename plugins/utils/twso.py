import json
from pathlib import Path

import requests

from taiko_bot.settings import get_settings

_SETTINGS = get_settings()
TWSO_DATA_PATH = _SETTINGS.root_dir / "songs" / "twso_data.json"


def update_twso_data():
    proxies = {"http": "socks5://127.0.0.1:7890", "https": "socks5://127.0.0.1:7890"}
    url = "https://taiko.namco-ch.net/taiko/twso2025/ranking/worldwide.php"
    html = requests.get(url, proxies=proxies).text
    marker = 'const search_json = "'
    start = html.find(marker)
    if start == -1:
        raise RuntimeError("没找到 search_json 定义")

    i = start + len(marker)
    escaped = False
    buf = []

    while i < len(html):
        ch = html[i]
        if not escaped:
            if ch == "\\":
                escaped = True
                buf.append(ch)
            elif ch == '"':
                break
            else:
                buf.append(ch)
        else:
            escaped = False
            buf.append(ch)
        i += 1

    raw_js_string = "".join(buf)
    decoded = bytes(raw_js_string, "utf-8").decode("unicode_escape")
    data = json.loads(decoded)
    TWSO_DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )


def find_player(taiko_no: str):
    with TWSO_DATA_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    cn_data = [item for item in data if len(str(item.get("taiko_no", ""))) < 10]
    cn_rank_map = {
        str(item.get("taiko_no")): index + 1
        for index, item in enumerate(cn_data)
    }
    for item in data:
        if str(item.get("taiko_no")) == str(taiko_no):
            result = dict(item)
            if str(item.get("taiko_no")) in cn_rank_map:
                result["cn_rank"] = cn_rank_map[str(item.get("taiko_no"))]
            return result
    return None
