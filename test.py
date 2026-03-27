import os
import requests
from datetime import datetime

# data = main.get_playlist_data("b77924fa-f2b0-46a2-944e-76b6f2d7ebf0")
# print(data)


# auth = "Bearer eyJhbGciOiJIUzI1NiIsImtpZCI6IjEyMTYiLCJ0eXAiOiJKV1QifQ.eyJqdGkiOiJmNDU4YmRhZS1kNjYwLTExZjAtOTE3Zi00MjAwNGU0OTQzMDAiLCJzdWIiOiJkZWQzZmQxZTk3MmQzMzNhIiwiZXhwIjoxNzY1NDQwODM1LCJpc3MiOiJsaXZlLXByb2R1Y3Rpb24iLCJpYXQiOjE3NjU0MzcyMzUsInR5cCI6ImJhc2ljIiwiY291bnRyeSI6IkhLIiwibmE6aWlkIjoiMDEzMDY3NzhiMmIwNmI0YmZjIiwibmE6bzEzIjoxLCJhYnRlc3RzIjoiIn0.w__b-MrAtkfTroZ-XdajdEBLYCSErUL1PaDK6Wu8vvg"
# url = "https://api.m.nintendo.com/catalog/users/ded3fd1e972d333a/sections/home"
# params = {
#     "lang": "zh-CN",
# }
# headers = {
#     'User-Agent': 'Nintendo Music/1.5.0 (com.nintendo.znba; build:25111915; iOS 26.1.0) Alamofire/5.10.2',
#     'authorization': auth,
# }
# response = requests.get(url, params=params, headers=headers, timeout=10)
# print(response.json())


def get_api(url: str, params: dict, retry_count: int = 5) -> dict | list:
    for _ in range(retry_count):
        try:
            headers = {
                'User-Agent': 'Nintendo Music/1.4.0 (com.nintendo.znba; build:25101508; iOS 26.1.0) Alamofire/5.10.2',
            }
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f'Error: {response.status_code}')
        except Exception as e:
            print(f'Error: {e}')
    print(f'Failed to get a successful response from the API after {retry_count} retries')
    # raise RuntimeError('Failed to get a successful response from the API after multiple retries')
    return []


# track_id = "bfac443c-402e-4242-8d35-9545b9d87453"
# url = f'https://api.m.nintendo.com/catalog/tracks/{track_id}'
# track_data = get_api(url, params={'country': 'JP', 'lang': 'zh-CN'})


url = "https://api.m.nintendo.com/catalog/resources:detectUpdates"
response = requests.get(url)
print(response.json())

updated_tracks = response.json().get("updatedTracks", [])
time = datetime.now().strftime('%Y-%m-%d')
path = f'detect_update/detect_update({time}).txt'
if not os.path.exists('detect_update'):
    os.makedirs('detect_update')
if os.path.exists(path):
    os.remove(path)

for track in updated_tracks:
    track_id = track.get("id")
    timestamp = track.get("updatedAt")
    # 将时间戳转换成年月日格式
    updated_date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    url = f'https://api.m.nintendo.com/catalog/tracks/{track_id}'

    track_data = get_api(url, params={'country': 'JP', 'lang': 'zh-CN'})
    if isinstance(track_data, dict):
        line = f"time: {updated_date}, ID: {track_id}, name: {track_data.get('name')}"
    else:
        line = f"time: {updated_date}, Failed to get data for track ID: {track_id}"

    print(line)

    with open(path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
