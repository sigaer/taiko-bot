from ...public.config import root
import json
import requests
import codecs




def find_player(taiko_no: str):
    with open(root() / "songs/twso_data.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    cn_data = [item for item in data if len(item["taiko_no"]) < 10]
    for item in cn_data:
        item["cn_rank"] = cn_data.index(item) + 1
    with open(root() / "songs/twso_cn_data.json", "w", encoding="utf-8") as f:
        json.dump(cn_data, f, ensure_ascii=False, indent=4)
    for item in data:
        if item["taiko_no"] == taiko_no:
            return item
    return None


# update_twso_data()
# print(find_player("2258735"))

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
    decoded = codecs.decode(raw_js_string, "unicode_escape")
    data = json.loads(decoded)
    with open(root() / "songs/twso_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
