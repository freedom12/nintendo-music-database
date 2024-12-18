import requests
import os
import re
import pandas as pd

# https://api.m.nintendo.com/catalog/games:all?country=JP&lang=en-US&sortRule=RECENT
# https://api.m.nintendo.com/catalog/gameGroups?country=JP&groupingPolicy=RELEASEDAT&lang=en-US
# https://api.m.nintendo.com/catalog/gameGroups?country=JP&groupingPolicy=HARDWARE&lang=en-US
# https://api.m.nintendo.com/catalog/games/e55a92d6-12f2-4011-8312-e7b38e2a3c7f/relatedPlaylists?country=JP&lang=zh-CN&membership=BASIC&packageType=hls_cbcs&sdkVersion=ios-1.4.0_f362763-1
# https://api.m.nintendo.com/catalog/officialPlaylists/772a2b39-c35d-43fd-b3b1-bf267c01f342?country=JP&lang=ja-JP&membership=BASIC&packageType=hls_cbcs&sdkVersion=ios-1.4.0_f362763-1

host = "https://api.m.nintendo.com"
IETF_list = ["zh-CN", "en-US", "ja-JP"]


def get_api(url: str, params: dict, retry_count: int = 5) -> dict:
    for i in range(retry_count):
        try:
            response = requests.get(url, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error: {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")
    exit(1)


def save_csv(file_path: str, data: list[dict], key_list: list[str]):
    with open(file_path, "a", encoding="utf-8") as file:
        file.write(",".join(key_list) + "\n")
        for item in data:
            value_list = [item[key] for key in key_list]
            for i in range(len(value_list)):
                value = value_list[i]
                if isinstance(value, str):
                    value = value.replace("\"", "\\\"")
                    value = f"\"{value}\""
                    value_list[i] = value
                elif isinstance(value, set):
                    value = "/".join(value)
                    value = value.replace("\"", "\\\"")
                    value = f"\"{value}\""
                    value_list[i] = value
            file.write(",".join(map(str, value_list)) + "\n")


def get_valid_filename(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '-', s.strip())


def gen_excel(IETF: str):
    path = os.path.join("output", IETF)
    if not os.path.exists(path):
        os.makedirs(path)

    url = f"{host}/catalog/games:all"
    game_data_list = get_api(url, {"country": "JP", "lang": IETF, "sortRule": "RECENT"})
    game_index = 0
    game_dict: dict = {}
    for game_data in game_data_list:
        print(f"{game_data["id"]} {game_data["name"]}")
        game_index = game_index + 1
        game = {
            "id": game_data["id"],
            "index": game_index,
            "name": game_data["name"],
            "year": 0,
            "hardware": game_data["formalHardware"],
            "isLink": game_data["isGameLink"],
            "thumbnailURL": game_data.get("thumbnailURL", "")
        }
        game_dict[game["id"]] = game

        if game["isLink"]:
            continue

        file_name = f"{game_data["name"]}.csv"
        file_name = get_valid_filename(file_name)
        file_path = os.path.join(path, file_name)
        if os.path.exists(file_path):
            continue

        url = f"{host}/catalog/games/{game_data["id"]}/relatedPlaylists"
        game_play_list_data = get_api(url, {"country": "JP", "lang": IETF, "membership": "BASIC", "packageType": "hls_cbcs", "sdkVersion": "ios-1.4.0_f362763-1"})
        all_play_list_id = game_play_list_data["allPlaylist"]["id"]
        url = f"{host}/catalog/officialPlaylists/{all_play_list_id}"
        all_play_list_data = get_api(url, {"country": "JP", "lang": IETF, "membership": "BASIC", "packageType": "hls_cbcs", "sdkVersion": "ios-1.4.0_f362763-1"})
        track_index = 0
        track_dict: dict = {}
        for track_data in all_play_list_data["tracks"]:
            payload_data = track_data["media"]["payloadList"][0]
            is_loop = payload_data["containsLoopableMedia"]

            if is_loop:
                duration = payload_data["loopableMedia"]["composed"]["durationMillis"]
                if payload_data["durationMillis"] != duration:
                    print(f"{game_data["name"]} {track_data["name"]} {payload_data["durationMillis"]} {duration}")
            else:
                duration = payload_data["durationMillis"]

            track_index = track_index + 1
            track = {
                "id": track_data["id"],
                "index": track_index,
                "name": track_data["name"],
                "duration": duration,
                "isLoop": is_loop,
                "isBest": False,
                "playlist": set[str](),
                "thumbnailURL": track_data.get("thumbnailURL", ""),
            }
            track_dict[track["id"]] = track

        for track_data in game_play_list_data["bestPlaylist"]["tracks"]:
            id = track_data["id"]
            if id in track_dict:
                track_dict[id]["isBest"] = True

        for plat_list_sum_data in game_play_list_data["miscPlaylistSet"]["officialPlaylists"]:
            if plat_list_sum_data["type"] == "LOOP":
                continue
            url = f"{host}/catalog/officialPlaylists/{plat_list_sum_data["id"]}"
            plat_list_data = get_api(url, {"country": "JP", "lang": IETF, "membership": "BASIC", "packageType": "hls_cbcs", "sdkVersion": "ios-1.4.0_f362763-1"})
            for track_data in plat_list_data["tracks"]:
                id = track_data["id"]
                if id in track_dict:
                    track_dict[id]["playlist"].add(plat_list_sum_data["name"])

        track_list = list(track_dict.values())
        track_list.sort(key=lambda x: x["index"])
        key_list = ["index", "name", "duration", "isLoop", "isBest", "playlist", "id", "thumbnailURL"]
        save_csv(file_path, track_list, key_list)

    url = f"{host}/catalog/gameGroups"
    game_group_data = get_api(url, {"country": "JP", "groupingPolicy": "RELEASEDAT", "lang": IETF})
    for group_data in game_group_data["releasedAt"]:
        year = group_data["releasedYear"]
        for game_data in group_data["items"]:
            id = game_data["id"]
            if id in game_dict:
                game_dict[id]["year"] = year
    count = len(game_dict)
    for game in game_dict.values():
        game["index"] = count - game["index"] + 1
    game_list = list(game_dict.values())
    game_list.sort(key=lambda x: x["index"])

    file_path = os.path.join(path, "game.csv")
    if os.path.exists(file_path):
        os.remove(file_path)

    key_list = ["index", "name", "year", "hardware", "isLink", "id", "thumbnailURL"]
    save_csv(file_path, game_list, key_list)

    csv_path_list = [os.path.join(path, file) for file in os.listdir(path) if file.endswith('.csv')]
    sheet_list: list = []
    for csv_path in csv_path_list:
        file_name = os.path.basename(csv_path)
        sheet_name = os.path.splitext(file_name)[0]
        index = 0
        for game in game_list:
            if get_valid_filename(game["name"]) == sheet_name:
                index = game["index"]
                break
        sheet_list.append({
            "index": index,
            "sheet_name": sheet_name,
            "csv_path": csv_path
        })
    sheet_list.sort(key=lambda x: x["index"])
    file_path = os.path.join("output", f"Nintendo Music {IETF}.xlsx")
    if os.path.exists(file_path):
        os.remove(file_path)
    with pd.ExcelWriter(file_path) as writer:
        for sheet in sheet_list:
            df = pd.read_csv(sheet["csv_path"], escapechar="\\")
            df.to_excel(writer, sheet_name=sheet["sheet_name"], index=False)


for IETF in IETF_list:
    gen_excel(IETF)

print("Done")
