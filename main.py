import concurrent.futures
import json
import math
import os
import re
from pathlib import Path
from typing import Iterable, Optional, TypedDict

import pandas as pd
import requests
# https://api.m.nintendo.com/catalog/games:all?country=JP&lang=en-US&sortRule=RECENT
# https://api.m.nintendo.com/catalog/gameGroups?country=JP&groupingPolicy=RELEASEDAT&lang=en-US
# https://api.m.nintendo.com/catalog/gameGroups?country=JP&groupingPolicy=HARDWARE&lang=en-US

# https://api.m.nintendo.com/catalog/games/e55a92d6-12f2-4011-8312-e7b38e2a3c7f?country=JP&lang=zh-CN
# https://api.m.nintendo.com/catalog/games/e55a92d6-12f2-4011-8312-e7b38e2a3c7f/relatedGames?country=JP&lang=zh-CN
# https://api.m.nintendo.com/catalog/games/e55a92d6-12f2-4011-8312-e7b38e2a3c7f/relatedPlaylists?country=JP&lang=zh-CN&membership=BASIC&packageType=hls_cbcs&sdkVersion=ios-1.4.0_f362763-1

# https://api.m.nintendo.com/catalog/officialPlaylists/772a2b39-c35d-43fd-b3b1-bf267c01f342?country=JP&lang=ja-JP&membership=BASIC&packageType=hls_cbcs&sdkVersion=ios-1.4.0_f362763-1

host = 'https://api.m.nintendo.com'
# lang_list = ['zh-TW', 'fr-FR', 'de-DE', 'it-IT', 'es-ES', 'ko-KR']
lang_list = ['zh-CN', 'en-US', 'ja-JP']  # IETF


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


def get_playlist_data(id, lang: str) -> dict:
    url = f'{host}/catalog/officialPlaylists/{id}'
    playlist_data = get_api(url, {'country': 'JP', 'lang': lang, 'membership': 'BASIC', 'packageType': 'hls_cbcs', 'sdkVersion': 'ios-1.4.0_f362763-1'})
    if not isinstance(playlist_data, dict):
        raise RuntimeError('Failed to get playlist data')
    return playlist_data


def get_related_playlist_data(id, lang: str) -> dict:
    url = f'{host}/catalog/games/{id}/relatedPlaylists'
    related_playlist_data = get_api(url, {'country': 'JP', 'lang': lang, 'membership': 'BASIC', 'packageType': 'hls_cbcs', 'sdkVersion': 'ios-1.4.0_f362763-1'})
    if not isinstance(related_playlist_data, dict):
        raise RuntimeError('Failed to get game related data')
    return related_playlist_data


def get_related_game_data_list(id, lang: str) -> list[dict]:
    url = f'{host}/catalog/games/{id}/relatedGames'
    related_game_data_list = get_api(url, {'country': 'JP', 'lang': lang})
    if not isinstance(related_game_data_list, list):
        raise RuntimeError('Failed to get game related data')
    return related_game_data_list


def get_all_game_data(lang: str) -> list[dict]:
    url = f'{host}/catalog/games:all'
    game_data_list = get_api(url, {'country': 'JP', 'lang': lang, 'sortRule': 'RECENT'})
    if not isinstance(game_data_list, list):
        raise RuntimeError('Failed to get all game data')
    return game_data_list


def get_game_group_data(grouping_policy: str, lang: str) -> dict:
    url = f'{host}/catalog/gameGroups'
    game_group_data = get_api(url, {'country': 'JP', 'groupingPolicy': grouping_policy, 'lang': lang})
    if not isinstance(game_group_data, dict):
        raise RuntimeError('Failed to get game group data')
    return game_group_data


def get_valid_filename(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '-', s.strip())


def save_csv(file_path: str, data: list, key_list: Optional[list[str]] = None):
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
                elif isinstance(value, set):
                    value = sorted(list(value))
                    value = '|'.join(value).replace('"', '\\"')
                    value_list[i] = f'"{value}"'
                elif isinstance(value, list):
                    value = '|'.join(value).replace('"', '\\"')
                    value_list[i] = f'"{value}"'
            file.write(','.join(map(str, value_list)) + '\n')


def gen_excel(lang: str):
    print(f'Generating {lang}...')
    path = Path('output') / lang
    path.mkdir(parents=True, exist_ok=True)

    game_data_list = get_all_game_data(lang)
    game_dict: dict[str, Game] = {}
    for game_index, game_data in enumerate(game_data_list, start=1):
        print(f'{game_data['id']} {game_data['name']}')
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
        related_game_data_list = get_related_game_data_list(game_data['id'], lang)
        for related_game_data in related_game_data_list:
            game['related_game'].add(related_game_data['name'])

        if game['is_link']:
            continue

        file_name = get_valid_filename(f'{game_data['name']}.csv')
        file_path = path / file_name
        if file_path.exists():
            continue

        related_playlist_data = get_related_playlist_data(game_data['id'], lang)
        track_data_list: list[dict] = get_playlist_data(related_playlist_data['allPlaylist']['id'], lang)['tracks']
        track_dict = game['track_dict']
        for track_index, track_data in enumerate(track_data_list, start=1):
            payload_data = track_data['media']['payloadList'][0]
            is_loop = payload_data['containsLoopableMedia']

            if is_loop:
                duration = payload_data['loopableMedia']['composed']['durationMillis']
                if payload_data['durationMillis'] != duration:
                    print(f'{game_data['name']} {track_data['name']} {payload_data['durationMillis']} {duration}')
            else:
                duration = payload_data['durationMillis']

            track: Track = {
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

    data = json.loads(open('nm.json', 'r', encoding='utf-8').read())
    for section_data in data['miscSections']:
        for play_list_sum_data in section_data['playlists']:
            playlist_data = get_playlist_data(play_list_sum_data['id'], lang)
            for track_data in playlist_data['tracks']:
                game_id = track_data['game']['id']
                track_id = track_data['id']
                if game_id in game_dict:
                    game = game_dict[game_id]
                    if track_id in game['track_dict']:
                        game['track_dict'][track_id]['playlist_2'].add(playlist_data['name'])

    for section_data in data['commonSections']:
        if section_data['name'] == '听听看吧':
            playlist_data = get_playlist_data(play_list_sum_data['id'], lang)
            for track_data in playlist_data['tracks']:
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
    with pd.ExcelWriter(file_path) as writer:
        for csv_path in csv_path_list:
            df = pd.read_csv(csv_path, escapechar='\\')
            if 'duration' in df.columns:
                df['duration'] = df['duration'].apply(lambda x: f'{x // 60000}:{math.ceil(x / 1000) % 60:02d}')
            df.to_excel(writer, sheet_name=csv_path.stem, index=False)


def main(is_concurrency: bool = False):
    if is_concurrency:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.map(gen_excel, lang_list)
    else:
        for lang in lang_list:
            gen_excel(lang)
    print('Done')


if __name__ == '__main__':
    main()
