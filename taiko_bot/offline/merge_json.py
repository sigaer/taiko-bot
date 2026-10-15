import json
from pathlib import Path


# 1. 读取两个 JSON 文件
def load_json(file_path: str | Path) -> list:
    """加载 JSON 文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


# 2. 合并 id 到 structured JSON 中
def merge_song_id_to_structured(songs_data: list, structured_data: dict) -> dict:
    """
    根据 song_name_jp 和 structured JSON 的曲名来匹配，并为结构化 JSON 中的每个曲目增加 id。
    如果无法匹配，不做修改。
    """
    song_name_to_id = {
        song["song_name_jp"]: {"id": song["id"], "song_name_cn": song["song_name"]}
        for song in songs_data
    }

    # 遍历 structured_data 中的每首歌曲
    for song_name, song_info in structured_data["songs"].items():
        # 查找匹配的 id，如果有则添加到每个曲目
        song_name_jp = song_info.get("曲名")  # structured JSON 中的曲名
        if "(裏)" in song_name_jp:
            song_name_jp = song_name_jp.replace("(裏)", "").strip()
            song_info["level"] = 5
        else:
            song_info["level"] = 4
        if song_name_jp in song_name_to_id:
            song_info["id"] = song_name_to_id[song_name_jp]["id"]
            song_info["song_name_cn"] = song_name_to_id[song_name_jp]["song_name_cn"]
        else:
            song_info["id"] = None  # 或者选择记录未匹配到的情况（例如：log）

    return structured_data


# 3. 保存合并后的 JSON
def save_json(data: dict, file_path: str | Path):
    """保存合并后的 JSON 数据"""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 4. 主程序
def main():
    # 读取歌曲数据文件和结构化 JSON 文件
    songs_data_path = Path("songs/song_data.json")  # 歌曲数据 JSON 文件路径
    structured_data_path = Path("songs/rating_structured.json")  # 结构化 JSON 文件路径

    # 1. 加载文件
    songs_data = load_json(songs_data_path)
    structured_data = load_json(structured_data_path)

    # 2. 合并 id
    merged_data = merge_song_id_to_structured(songs_data, structured_data)

    # 3. 保存结果到新文件
    save_json(merged_data, "songs/rating_structured_with_ids.json")
    print("合并完成，已保存到 'songs/rating_structured_with_ids.json'")


if __name__ == "__main__":
    main()
