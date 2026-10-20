# 本地记录：每个 UID 一个 json 文件，放在 data/ 下。合并时按记录 id 去重。
import os, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, 'data')
SETTINGS = os.path.join(HERE, 'settings.json')


def _path(uid):
    return os.path.join(DATA_DIR, f'{uid}.json')


def uids():
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(DATA_DIR) if f.endswith('.json') and f[:-5].isdigit())


def load(uid):
    try:
        with open(_path(uid), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'uid': uid, 'region_time_zone': 8, 'updated_at': '', 'records': []}


def save(doc):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = _path(doc['uid']) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(doc['uid']))     # 先写临时文件再替换，写到一半断电也不会坏掉原文件


def known_ids(uid):
    return {r['id'] for r in load(uid)['records']}


def merge(uid, tz, new_records):
    """把新记录并入本地文件，返回 {卡池: 新增条数}。"""
    doc = load(uid)
    have = {r['id'] for r in doc['records']}
    added = {}
    for r in new_records:
        if r['id'] in have:
            continue
        have.add(r['id'])
        doc['records'].append({k: r.get(k, '') for k in ('id', 'gacha_type', 'gacha_id', 'item_id', 'name', 'item_type', 'rank_type', 'time')})
        added[r['gacha_type']] = added.get(r['gacha_type'], 0) + 1
    doc['records'].sort(key=lambda r: int(r['id']))
    doc['region_time_zone'] = tz
    doc['updated_at'] = time.strftime('%Y-%m-%d %H:%M')
    save(doc)
    return added


def load_settings():
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    with open(SETTINGS, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
