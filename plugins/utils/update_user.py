from concurrent.futures import ThreadPoolExecutor
import requests
import ujson as json
from taiko_bot.settings import get_settings

from .dojo_score import normalize_dojo_scores
from .userdata_storage import save_userdata


### 这里是全量返回
def getUserData(user_id):
    with (get_settings().root_dir / "config.json").open("r", encoding="utf-8") as f:
        config = json.load(f)
    AUTHORIZATION = config["cookie"]
    url = "https://wl-taiko.wahlap.net/api/user/all/songs"
    data = {
        "page": 1,
        "pageSize": 3000,
        "sort": 1,
        "isPlayed": True,
        "userid": user_id,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541020) XWEB/16459",
        "Content-Type": "application/json",
        "Referer": "https://servicewechat.com/wxeafab0667490cd23/21/page-frame.html",
        "Authorization": AUTHORIZATION,
    }
    search_url = "https://wl-taiko.wahlap.net/api/user/search/player"
    search_data = {"keyword": user_id, "page": 1, "pageSize": 10}
    profile_url = f"https://wl-taiko.wahlap.net/api/game/player/achievement/{user_id}"
    dojo_score_url = f"https://wl-taiko.wahlap.net/api/game/dojo/score/{user_id}"

    with ThreadPoolExecutor(max_workers=4) as executor:
        song_future = executor.submit(requests.post, url, json=data, headers=headers)
        search_future = executor.submit(
            requests.post, search_url, json=search_data, headers=headers
        )
        profile_future = executor.submit(requests.get, profile_url, headers=headers)
        dojo_future = executor.submit(requests.get, dojo_score_url, headers=headers)
        song_response = song_future.result()
        search_response = search_future.result()
        prof_response = profile_future.result()
        dojo_response = dojo_future.result()

    if song_response.status_code not in [200, 201]:
        return -1
    res = song_response.json()
    if res["message"] == "用户不存在":
        return 404
    song_list = res["data"]["playedRecords"]["scoreInfo"]
    for song in song_list:
        try:
            del song["song_detail"]
            del song["tone_flg"]
        except KeyError:
            pass

    if search_response.status_code not in [200, 201]:
        return -1
    res = search_response.json()
    panel_data = res["data"]["players"][0]

    if prof_response.status_code not in [200, 201]:
        return -1
    prof_res = prof_response.json()
    count_data = prof_res["data"]
    if dojo_response.status_code not in [200, 201]:
        return -1
    dojo_res = dojo_response.json()
    dojo_data = normalize_dojo_scores(dojo_res)
    userdata = {
        "profile": panel_data,
        "songs": song_list,
        "achievement": count_data,
        "dojo": dojo_data,
    }
    save_userdata(user_id, userdata, source="wahlap")
    return 0
