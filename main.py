import concurrent.futures
import csv
import json
import math
import re
import threading
import time
import warnings
from pathlib import Path
from typing import Optional, TypedDict

import pandas as pd
import requests
# https://www.nintendo.com/hk/nintendo-music/titles/ 可查询游戏曲目更新日期

# https://api.m.nintendo.com/catalog/games:all?country=JP&lang=en-US&sortRule=RECENT
# https://api.m.nintendo.com/catalog/gameGroups?country=JP&groupingPolicy=RELEASEDAT&lang=en-US
# https://api.m.nintendo.com/catalog/gameGroups?country=JP&groupingPolicy=HARDWARE&lang=en-US

# https://api.m.nintendo.com/catalog/games/e55a92d6-12f2-4011-8312-e7b38e2a3c7f?country=JP&lang=zh-CN
# https://api.m.nintendo.com/catalog/games/e55a92d6-12f2-4011-8312-e7b38e2a3c7f/relatedGames?country=JP&lang=zh-CN
# https://api.m.nintendo.com/catalog/games/e55a92d6-12f2-4011-8312-e7b38e2a3c7f/relatedPlaylists?country=JP&lang=zh-CN&membership=BASIC&packageType=hls_cbcs&sdkVersion=ios-1.4.0_f362763-1

# https://api.m.nintendo.com/catalog/officialPlaylists/772a2b39-c35d-43fd-b3b1-bf267c01f342?country=JP&lang=ja-JP&membership=BASIC&packageType=hls_cbcs&sdkVersion=ios-1.4.0_f362763-1
# https://api.m.nintendo.com/catalog/officialPlaylists/772a2b39-c35d-43fd-b3b1-bf267c01f342?country=JP&lang=ja-JP&membership=BASIC&packageType=hls_clear&sdkVersion=ios-1.4.0_f362763-1

# https://api.m.nintendo.com/catalog/tracks/3ab255bc-5d15-452c-9cfd-ae3037efaa34?country=JP&lang=zh-CN
# https://api.m.nintendo.com/catalog/resources:search?country=HK&lang=zh-CN&limit=100&membership=BASIC&packageType=hls_cbcs&q=mario&sdkVersion=ios-1.8.3_19a0d8f9-1
# https://api.m.nintendo.com/catalog/notices?country=HK&lang=zh-CN&limit=20&platformType=iOS
# https://api.m.nintendo.com/catalog/contentNotices:filterByHome?country=HK&lang=zh-CN&limit=10
# https://api.m.nintendo.com/catalog/resources:detectUpdates

host = 'https://api.m.nintendo.com'
lang_list = ['zh-CN', 'en-US', 'ja-JP', 'zh-TW', 'fr-FR', 'de-DE', 'it-IT', 'es-ES', 'ko-KR']

# ============ 并发与连接复用（提速核心） ============
# 全局信号量：限制所有线程同时进行的 HTTP 请求总数。
MAX_CONCURRENT_REQUESTS = 32
_request_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
_print_lock = threading.Lock()
_thread_local = threading.local()
# 播放列表磁盘缓存目录：跨运行复用；数据过期时删除该目录即可强制刷新
playlist_cache_dir = Path('playlist_cache')


def log(msg: str):
    """多线程下安全打印，flush 保证在 VS Code 终端实时可见（否则输出被缓冲，像卡死）。"""
    with _print_lock:
        print(msg, flush=True)


def get_session() -> requests.Session:
    """每个线程复用一个 Session：开启 keep-alive，复用 TCP 连接，省去每次请求的握手开销。"""
    session = getattr(_thread_local, 'session', None)
    if session is None:
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0)
        session.mount('https://', adapter)
        _thread_local.session = session
    return session


class Game(TypedDict):
    id: str
    index: int
    name: str
    year: int
    hardware: str
    related_game: set[str]
    is_link: bool
    thumbnail_url: str
    track_dict: dict[str, 'Track']


class Track(TypedDict):
    id: str
    index: int
    name: str
    duration: int
    is_loop: bool
    is_best: bool
    playlist: set[str]
    playlist_2: set[str]
    playlist_3: set[str]
    thumbnail_url: str


def get_api(url: str, params: dict, retry_count: int = 5) -> dict | list:
    for attempt in range(retry_count):
        try:
            headers = {
                'User-Agent': 'Nintendo Music/1.4.0 (com.nintendo.znba; build:25101508; iOS 26.1.0) Alamofire/5.10.2',
            }
            with _request_semaphore:
                response = get_session().get(url, params=params, headers=headers, timeout=2)
            if response.status_code == 200:
                return response.json()
            else:
                log(f'Error: {response.status_code}')
        except Exception as e:
            log(f'Error: {e}')
        if attempt < retry_count - 1:
            # 指数退避：被限流（RST）时疯狂重试只会加重限流并拖延整体进度
            time.sleep(min(1.5 * (2 ** attempt), 8))
    raise RuntimeError('Failed to get a successful response from the API after multiple retries')


def get_track_data(id: str, lang: str = 'zh-CN') -> dict:
    url = f'{host}/catalog/tracks/{id}'
    track_data = get_api(url, {'country': 'JP', 'lang': lang, 'membership': 'BASIC', 'packageType': 'hls_clear', 'sdkVersion': 'ios-1.4.0_f362763-1'})
    if not isinstance(track_data, dict):
        raise RuntimeError('Failed to get track data')
    return track_data


playlist_data_dict: dict[str, dict[str, dict]] = {}


def get_playlist_data(id, lang: str = 'zh-CN') -> dict:
    log(f'Getting playlist data: {id} ({lang})')
    cached = playlist_data_dict.setdefault(lang, {}).get(id)
    if cached is not None:
        return cached
    cache_file = playlist_cache_dir / lang / f'{id}.json'
    if cache_file.exists():
        try:
            playlist_data = json.loads(cache_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            pass  # 缓存损坏则忽略，重新请求
        else:
            playlist_data_dict[lang][id] = playlist_data
            return playlist_data
    url = f'{host}/catalog/officialPlaylists/{id}'
    playlist_data = get_api(url, {'country': 'JP', 'lang': lang, 'membership': 'BASIC', 'packageType': 'hls_cbcs', 'sdkVersion': 'ios-1.4.0_f362763-1'})
    if not isinstance(playlist_data, dict):
        raise RuntimeError('Failed to get playlist data')
    playlist_data_dict[lang][id] = playlist_data
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    # 通过临时文件 + 原子替换写入，避免并发写坏缓存
    tmp_file = cache_file.with_name(f'{cache_file.name}.{threading.get_ident()}.tmp')
    tmp_file.write_text(json.dumps(playlist_data, ensure_ascii=False), encoding='utf-8')
    tmp_file.replace(cache_file)
    return playlist_data


def get_related_playlist_data(id, lang: str = 'zh-CN') -> dict:
    url = f'{host}/catalog/games/{id}/relatedPlaylists'
    related_playlist_data = get_api(url, {'country': 'JP', 'lang': lang, 'membership': 'BASIC', 'packageType': 'hls_cbcs', 'sdkVersion': 'ios-1.4.0_f362763-1'})
    if not isinstance(related_playlist_data, dict):
        raise RuntimeError('Failed to get game related data')
    return related_playlist_data


def get_related_game_data_list(id, lang: str = 'zh-CN') -> list[dict]:
    url = f'{host}/catalog/games/{id}/relatedGames'
    related_game_data_list = get_api(url, {'country': 'JP', 'lang': lang})
    if not isinstance(related_game_data_list, list):
        raise RuntimeError('Failed to get game related data')
    return related_game_data_list


def get_all_game_data(lang: str = 'zh-CN') -> list[dict]:
    url = f'{host}/catalog/games:all'
    game_data_list = get_api(url, {'country': 'JP', 'lang': lang, 'sortRule': 'RECENT'})
    if not isinstance(game_data_list, list):
        raise RuntimeError('Failed to get all game data')
    return game_data_list


game_group_data_cache: dict[str, dict] = {}


def get_game_group_data(grouping_policy: str, lang: str = 'zh-CN') -> dict:
    # 这里只用到 id 与 releasedYear，均与语言无关：按 policy 缓存，多语言全量生成时仅请求一次
    if grouping_policy in game_group_data_cache:
        return game_group_data_cache[grouping_policy]
    url = f'{host}/catalog/gameGroups'
    game_group_data = get_api(url, {'country': 'JP', 'groupingPolicy': grouping_policy, 'lang': lang})
    if not isinstance(game_group_data, dict):
        raise RuntimeError('Failed to get game group data')
    game_group_data_cache[grouping_policy] = game_group_data
    return game_group_data


def get_valid_filename(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '-', s.strip())


def save_csv(file_path: str, data: list, key_list: Optional[list[str]] = None):
    if not key_list:
        key_list = list(data[0].keys())
    with open(file_path, 'w', encoding='utf-8') as file:
        log(f'Saving CSV: {file_path}')
        file.write(','.join(key_list) + '\n')
        for item in data:
            value_list = [item[key] for key in key_list]
            for i, value in enumerate(value_list):
                if isinstance(value, str):
                    value = value.replace('"', '\\"')
                    value_list[i] = f'"{value}"'
                elif isinstance(value, set):
                    value = sorted(list(value))
                    value = '|'.join(value).replace('"', '\\"')
                    value_list[i] = f'"{value}"'
                elif isinstance(value, list):
                    value = '|'.join(value).replace('"', '\\"')
                    value_list[i] = f'"{value}"'
            file.write(','.join(map(str, value_list)) + '\n')


def load_track_csv(file_path: str) -> list[Track]:
    track_list = []
    index = 0
    with open(file_path, 'r', encoding='utf-8') as file:
        reader = csv.reader(file, escapechar="\\")
        for row in reader:
            if index == 0:
                key_list = row
            else:
                value_list = row
                item: dict = {}
                for i, key in enumerate(key_list):
                    item[key] = value_list[i]
                track: Track = {
                    'id': item['id'],
                    'index': int(item['index']),
                    'name': item['name'],
                    'duration': int(item['duration']),
                    'is_loop': item['is_loop'] == 'True',
                    'is_best': item['is_best'] == 'True',
                    'playlist': set(item['playlist'].split('|')) if item['playlist'] else set(),
                    'playlist_2': set(item['playlist_2'].split('|')) if item['playlist_2'] else set(),
                    'playlist_3': set(item['playlist_3'].split('|')) if item['playlist_3'] else set(),
                    'thumbnail_url': item.get('thumbnail_url', ''),
                }
                track_list.append(track)
            index += 1
    return track_list


def process_game(game: Game, lang: str, path: Path, related_game_cache: dict[str, set[str]]) -> None:
    """获取单个游戏的数据并填充 game（related_game 与 track_dict）。每个游戏数据独立，可并发执行。"""
    if game['id'] in related_game_cache:
        game['related_game'] = related_game_cache[game['id']]
    else:
        related_game_data_list = get_related_game_data_list(game['id'], lang)
        for related_game_data in related_game_data_list:
            game['related_game'].add(related_game_data['name'])

    if game['is_link']:
        return

    file_name = get_valid_filename(f"{game['name']}.csv")
    file_path = path / file_name
    if file_path.exists():
        for track in load_track_csv(str(file_path)):
            game['track_dict'][track['id']] = track
        return

    related_playlist_data = get_related_playlist_data(game['id'], lang)
    track_data_list: list[dict] = get_playlist_data(related_playlist_data['allPlaylist']['id'], lang)['tracks']
    track_dict = game['track_dict']
    for track_index, track_data in enumerate(track_data_list, start=1):
        payload_data = track_data['media']['payloadList'][0]
        is_loop = payload_data['containsLoopableMedia']

        if is_loop:
            duration = payload_data['loopableMedia']['composed']['durationMillis']
            if payload_data['durationMillis'] != duration:
                log(f"{game['name']} {track_data['name']} {payload_data['durationMillis']} {duration}")
        else:
            duration = payload_data['durationMillis']

        track = {
            'id': track_data['id'],
            'index': track_index,
            'name': track_data['name'],
            'duration': duration,
            'is_loop': is_loop,
            'is_best': False,
            'playlist': set(),
            'playlist_2': set(),
            'playlist_3': set(),
            'thumbnail_url': track_data.get('thumbnailURL', ''),
        }
        track_dict[track['id']] = track

    for track_data in related_playlist_data['bestPlaylist']['tracks']:
        track_dict[track_data['id']]['is_best'] = True

    for play_list_sum_data in related_playlist_data['miscPlaylistSet']['officialPlaylists']:
        if play_list_sum_data['type'] == 'LOOP':
            continue
        track_data_list = get_playlist_data(play_list_sum_data['id'], lang)['tracks']
        for track_data in track_data_list:
            track_id = track_data['id']
            if track_id in track_dict:
                track_dict[track_id]['playlist'].add(play_list_sum_data['name'])


def gen_excel(lang: str):
    log(f'Generating {lang}...')
    path = Path('output') / lang
    path.mkdir(parents=True, exist_ok=True)

    game_data_list = get_all_game_data(lang)
    game_dict: dict[str, Game] = {}
    for game_index, game_data in enumerate(game_data_list, start=1):
        log(f"{game_data['id']} {game_data['name']}")
        game: Game = {
            'id': game_data['id'],
            'index': len(game_data_list) - game_index + 1,
            'name': game_data['name'],
            'year': 0,
            'hardware': game_data['formalHardware'],
            'related_game': set(),
            'is_link': game_data['isGameLink'],
            'thumbnail_url': game_data.get('thumbnailURL', ''),
            'track_dict': {}
        }
        game_dict[game['id']] = game

    # 从上次生成的 _GAME_LIST_.csv 读取 related_game 缓存，省去每个游戏一次 relatedGames 请求
    related_game_cache: dict[str, set[str]] = {}
    game_list_path = path / '_GAME_LIST_.csv'
    if game_list_path.exists():
        with open(game_list_path, 'r', encoding='utf-8') as file:
            reader = csv.reader(file, escapechar='\\')
            header = next(reader, None) or []
            for row in reader:
                if len(row) != len(header):
                    continue
                item = dict(zip(header, row))
                if item.get('id'):
                    related_game_cache[item['id']] = set(item['related_game'].split('|')) if item['related_game'] else set()

    # 游戏级并发：每个游戏一个任务（游戏数远大于线程数，并行度足够）
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
        future_list = [executor.submit(process_game, game, lang, path, related_game_cache) for game in game_dict.values()]
        for future in concurrent.futures.as_completed(future_list):
            future.result()

    data = json.loads(open('home.json', 'r', encoding='utf-8').read())

    # 先并发预取 home.json 涉及的全部播放列表（内存/磁盘缓存命中则跳过），后续循环纯本地操作
    playlist_id_list: list[str] = []
    for section_data in data['miscSections']:
        for play_list_sum_data in section_data['playlists']:
            playlist_id_list.append(play_list_sum_data['id'])
    for section_data in data['commonSections']:
        if section_data['name'] != '听听看吧':
            continue
        for play_list_sum_data in section_data['playlists']:
            playlist_id_list.append(play_list_sum_data['id'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as playlist_executor:
        list(playlist_executor.map(lambda playlist_id: get_playlist_data(playlist_id, lang), dict.fromkeys(playlist_id_list)))

    for section_data in data['miscSections']:
        for play_list_sum_data in section_data['playlists']:
            playlist_data = get_playlist_data(play_list_sum_data['id'], lang)
            for track_data in playlist_data['tracks']:
                if not 'game' in track_data or not track_data['game']:
                    continue
                game_id = track_data['game']['id']
                track_id = track_data['id']
                if game_id in game_dict:
                    game = game_dict[game_id]
                    if track_id in game['track_dict']:
                        game['track_dict'][track_id]['playlist_2'].add(playlist_data['name'])

    for section_data in data['commonSections']:
        if section_data['name'] != '听听看吧':
            continue
        for play_list_sum_data in section_data['playlists']:
            playlist_data = get_playlist_data(play_list_sum_data['id'], lang)
            for track_data in playlist_data['tracks']:
                if not 'game' in track_data or not track_data['game']:
                    continue
                game_id = track_data['game']['id']
                track_id = track_data['id']
                if game_id in game_dict:
                    game = game_dict[game_id]
                    if track_id in game['track_dict']:
                        game['track_dict'][track_id]['playlist_3'].add(playlist_data['name'])

    game_group_data = get_game_group_data('RELEASEDAT', lang)
    for group_data in game_group_data['releasedAt']:
        year = group_data['releasedYear']
        for game_data in group_data['items']:
            if game_data['id'] in game_dict:
                game_dict[game_data['id']]['year'] = year

    game_list = sorted(game_dict.values(), key=lambda x: x['index'])

    file_path = path / '_GAME_LIST_.csv'
    if file_path.exists():
        file_path.unlink()

    key_list = ['index', 'name', 'year', 'hardware', 'related_game', 'is_link', 'id', 'thumbnail_url']
    save_csv(str(file_path), game_list, key_list)

    csv_path_list: list[Path] = []
    for game in game_list:
        file_name = get_valid_filename(f'{game['name']}.csv')
        file_path = path / file_name
        if not game['is_link']:
            csv_path_list.append(file_path)
        if not game['track_dict']:
            continue
        track_list = sorted(game['track_dict'].values(), key=lambda x: x['index'])
        key_list = ['index', 'name', 'duration', 'is_loop', 'is_best', 'playlist', 'playlist_2', 'playlist_3', 'id', 'thumbnail_url']
        save_csv(str(file_path), track_list, key_list)

    csv_path_list.insert(0, path / '_GAME_LIST_.csv')
    file_path = Path('output') / f'Nintendo Music Database({lang}).xlsx'
    if file_path.exists():
        file_path.unlink()
    log(f'Generating Excel: {file_path}')
    with warnings.catch_warnings():
        # 保留完整工作表名（目标软件可正常读取超长标题），只屏蔽 openpyxl 的长度提示。
        # 注意：message 参数是"从消息开头匹配"的正则，必须写完整开头文本
        warnings.filterwarnings('ignore', message='Title is more than 31 characters', module='openpyxl')
        with pd.ExcelWriter(file_path) as writer:
            for csv_path in csv_path_list:
                df = pd.read_csv(csv_path, escapechar='\\')
                if 'duration' in df.columns:
                    df['duration'] = df['duration'].apply(lambda x: f'{x // 60000}:{math.ceil(x / 1000) % 60:02d}')
                df.to_excel(writer, sheet_name=csv_path.stem, index=False)


def main(is_concurrency: bool = True):
    if is_concurrency:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(lang_list)) as executor:
            list(executor.map(gen_excel, lang_list))
    else:
        for lang in lang_list:
            gen_excel(lang)
    print('Done', flush=True)


if __name__ == '__main__':
    main()
