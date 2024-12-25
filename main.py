import concurrent.futures
import math
import os
import re
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests
# https://api.m.nintendo.com/catalog/games:all?country=JP&lang=en-US&sortRule=RECENT
# https://api.m.nintendo.com/catalog/gameGroups?country=JP&groupingPolicy=RELEASEDAT&lang=en-US
# https://api.m.nintendo.com/catalog/gameGroups?country=JP&groupingPolicy=HARDWARE&lang=en-US
# https://api.m.nintendo.com/catalog/games/e55a92d6-12f2-4011-8312-e7b38e2a3c7f/relatedPlaylists?country=JP&lang=zh-CN&membership=BASIC&packageType=hls_cbcs&sdkVersion=ios-1.4.0_f362763-1
# https://api.m.nintendo.com/catalog/officialPlaylists/772a2b39-c35d-43fd-b3b1-bf267c01f342?country=JP&lang=ja-JP&membership=BASIC&packageType=hls_cbcs&sdkVersion=ios-1.4.0_f362763-1

host = 'https://api.m.nintendo.com'
IETF_list = ['zh-CN', 'en-US', 'ja-JP']


def get_api(url: str, params: dict, retry_count: int = 5) -> dict:
    for _ in range(retry_count):
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f'Error: {response.status_code}')
        except Exception as e:
            print(f'Error: {e}')
    raise RuntimeError('Failed to get a successful response from the API after multiple retries')


def save_csv(file_path: str, data: list[dict], key_list: Optional[list[str]] = None):
    if not key_list:
        key_list = list(data[0].keys())
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(','.join(key_list) + '\n')
        for item in data:
            value_list = [item[key] for key in key_list]
            for i, value in enumerate(value_list):
                if isinstance(value, str):
                    value = value.replace('"', '\\"')
                    value_list[i] = f'"{value}"'
                elif isinstance(value, Iterable):
                    value = sorted(list(value))
                    value = '|'.join(value).replace('"', '\\"')
                    value_list[i] = f'"{value}"'
            file.write(','.join(map(str, value_list)) + '\n')


def get_valid_filename(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '-', s.strip())


def gen_excel(IETF: str):
    path = Path('output') / IETF
    path.mkdir(parents=True, exist_ok=True)

    url = f'{host}/catalog/games:all'
    game_data_list = get_api(url, {'country': 'JP', 'lang': IETF, 'sortRule': 'RECENT'})
    game_dict = {}
    for game_index, game_data in enumerate(game_data_list, start=1):
        print(f"{game_data['id']} {game_data['name']}")
        game = {
            'id': game_data['id'],
            'index': game_index,
            'name': game_data['name'],
            'year': 0,
            'hardware': game_data['formalHardware'],
            'isLink': game_data['isGameLink'],
            'thumbnailURL': game_data.get('thumbnailURL', '')
        }
        game_dict[game['id']] = game

        if game['isLink']:
            continue

        file_name = get_valid_filename(f"{game_data['name']}.csv")
        file_path = path / file_name
        if file_path.exists():
            continue

        url = f'{host}/catalog/games/{game_data["id"]}/relatedPlaylists'
        game_play_list_data = get_api(url, {'country': 'JP', 'lang': IETF, 'membership': 'BASIC', 'packageType': 'hls_cbcs', 'sdkVersion': 'ios-1.4.0_f362763-1'})
        all_play_list_id = game_play_list_data['allPlaylist']['id']
        url = f'{host}/catalog/officialPlaylists/{all_play_list_id}'
        all_play_list_data = get_api(url, {'country': 'JP', 'lang': IETF, 'membership': 'BASIC', 'packageType': 'hls_cbcs', 'sdkVersion': 'ios-1.4.0_f362763-1'})
        track_dict = {}
        for track_index, track_data in enumerate(all_play_list_data['tracks'], start=1):
            payload_data = track_data['media']['payloadList'][0]
            is_loop = payload_data['containsLoopableMedia']

            if is_loop:
                duration = payload_data['loopableMedia']['composed']['durationMillis']
                if payload_data['durationMillis'] != duration:
                    print(f'{game_data["name"]} {track_data["name"]} {payload_data["durationMillis"]} {duration}')
            else:
                duration = payload_data['durationMillis']

            track = {
                'id': track_data['id'],
                'index': track_index,
                'name': track_data['name'],
                'duration': duration,
                'isLoop': is_loop,
                'isBest': False,
                'playlist': set(),
                'thumbnailURL': track_data.get('thumbnailURL', ''),
            }
            track_dict[track['id']] = track

        for track_data in game_play_list_data['bestPlaylist']['tracks']:
            track_dict[track_data['id']]['isBest'] = True

        for plat_list_sum_data in game_play_list_data['miscPlaylistSet']['officialPlaylists']:
            if plat_list_sum_data['type'] == 'LOOP':
                continue
            url = f'{host}/catalog/officialPlaylists/{plat_list_sum_data["id"]}'
            plat_list_data = get_api(url, {'country': 'JP', 'lang': IETF, 'membership': 'BASIC', 'packageType': 'hls_cbcs', 'sdkVersion': 'ios-1.4.0_f362763-1'})
            for track_data in plat_list_data['tracks']:
                id = track_data['id']
                if id in track_dict:
                    track_dict[id]['playlist'].add(plat_list_sum_data['name'])

        track_list = sorted(track_dict.values(), key=lambda x: x['index'])
        key_list = ['index', 'name', 'duration', 'isLoop', 'isBest', 'playlist', 'id', 'thumbnailURL']
        save_csv(str(file_path), track_list, key_list)

    url = f'{host}/catalog/gameGroups'
    game_group_data = get_api(url, {'country': 'JP', 'groupingPolicy': 'RELEASEDAT', 'lang': IETF})
    for group_data in game_group_data['releasedAt']:
        year = group_data['releasedYear']
        for game_data in group_data['items']:
            if game_data['id'] in game_dict:
                game_dict[game_data['id']]['year'] = year

    game_list = sorted(game_dict.values(), key=lambda x: x['index'], reverse=True)
    for game in game_list:
        game['index'] = len(game_list) - game['index'] + 1

    file_path = path / 'game.csv'
    if file_path.exists():
        file_path.unlink()

    key_list = ['index', 'name', 'year', 'hardware', 'isLink', 'id', 'thumbnailURL']
    save_csv(str(file_path), game_list, key_list)

    csv_path_list = [path / file for file in os.listdir(path) if file.endswith('.csv')]
    sheet_list: list = []
    for csv_path in csv_path_list:
        sheet_name = csv_path.stem
        index = 0
        for game in game_list:
            if get_valid_filename(game['name']) == sheet_name:
                index = game['index']
                break
        sheet_list.append({
            'index': index,
            'sheet_name': sheet_name,
            'csv_path': str(csv_path)
        })
    sheet_list.sort(key=lambda x: x['index'])

    file_path = Path('output') / f'Nintendo Music Database({IETF}).xlsx'
    if file_path.exists():
        file_path.unlink()
    with pd.ExcelWriter(file_path) as writer:
        for sheet in sheet_list:
            df = pd.read_csv(sheet['csv_path'], escapechar='\\')
            if 'duration' in df.columns:
                df['duration'] = df['duration'].apply(lambda x: f'{x // 60000}:{math.ceil(x / 1000) % 60:02d}')
            df.to_excel(writer, sheet_name=sheet['sheet_name'], index=False)


def main(is_concurrency: bool = False):
    if is_concurrency:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.map(gen_excel, IETF_list)
    else:
        for IETF in IETF_list:
            gen_excel(IETF)
    print('Done')


if __name__ == '__main__':
    main(True)
