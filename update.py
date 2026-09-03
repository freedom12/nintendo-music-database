import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter

# 每个线程复用各自的 Session(连接池),省去重复 TCP 握手,显著加速批量请求
_thread_local = threading.local()


def _get_session() -> requests.Session:
    if not hasattr(_thread_local, 'session'):
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=0)
        session.mount('https://', adapter)
        _thread_local.session = session
    return _thread_local.session

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
    # 并发时不再直接 print,避免多线程日志互相穿插错乱;
    # 失败信息由调用方统一按原始顺序输出。
    session = _get_session()
    for _ in range(retry_count):
        try:
            headers = {
                'User-Agent': 'Nintendo Music/1.4.0 (com.nintendo.znba; build:25101508; iOS 26.1.0) Alamofire/5.10.2',
            }
            response = session.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 400:
                return []
        except Exception:
            pass
    return []


# track_id = "bfac443c-402e-4242-8d35-9545b9d87453"
# url = f'https://api.m.nintendo.com/catalog/tracks/{track_id}'
# track_data = get_api(url, params={'country': 'JP', 'lang': 'zh-CN'})


def _build_line(track: dict) -> str:
    track_id = track.get("id")
    timestamp = track.get("updatedAt") or 0
    # 将时间戳转换成年月日格式
    updated_date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    track_url = f'https://api.m.nintendo.com/catalog/tracks/{track_id}'
    track_data = get_api(track_url, params={'country': 'JP', 'lang': 'zh-CN'})
    if isinstance(track_data, dict):
        return f"time: {updated_date}, ID: {track_id}, name: {track_data.get('name')}"
    return f"time: {updated_date}, Failed to get data for track ID: {track_id}"


url = "https://api.m.nintendo.com/catalog/resources:detectUpdates"
data = requests.get(url).json()
print(data)

updated_tracks = data.get("updatedTracks", [])
time = datetime.now().strftime('%Y-%m-%d')
path = f'detect_update/detect_update({time}).txt'
if not os.path.exists('detect_update'):
    os.makedirs('detect_update')
if os.path.exists(path):
    os.remove(path)

# 并发抓取全部 track,结果按原始下标放回,保证日志顺序不被打乱
lines: list[str] = [""] * len(updated_tracks)
with ThreadPoolExecutor(max_workers=32) as executor:
    futures = {
        executor.submit(_build_line, track): index
        for index, track in enumerate(updated_tracks)
    }
    for future in as_completed(futures):
        index = futures[future]
        try:
            lines[index] = future.result()
        except Exception as e:
            lines[index] = f'Error: {e}'

# 按原始顺序打印,并一次性写入文件(避免逐行 open/close)
for line in lines:
    print(line)

if lines:
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
