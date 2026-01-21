import os
import requests
import main
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
    response = requests.get(url, params={'country': 'JP', 'lang': 'zh-CN'})
    if response.status_code == 200:
        track_data = response.json()
        str = f"time: {updated_date}, ID: {track_id}, name: {track_data.get('name')}"
    else:
        str = f"time: {updated_date}, Failed to get data for track ID: {track_id}"

    print(str)

    with open(path, 'a', encoding='utf-8') as f:
        f.write(str + '\n')
