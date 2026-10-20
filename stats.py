# 统计：保底计数、每个五星用了多少抽、歪没歪
# 官方接口只能查到约一年；更早的五星来自小黑盒截图，存在 data/<uid>.json 的 legacy 里，接在官方记录前面
#
# 歪没歪怎么判断（3.2 版本起角色池的歪池是玩家在「星缘相邀」里自选的 7 人，所以没有通用名单）：
#   1. 用户手动标过的（doc['overrides']）为准
#   2. 同一个卡池（gacha_id）里出过不同的五星：出得最多的是 UP，其余是歪
#   3. 卡池里只出过一种五星：在歪池名单（standard.json：常驻 + 星缘相邀 + 光锥）里就算歪
import os, json
from collections import Counter
from dataclasses import dataclass, field
from gacha_api import POOLS

LIMITED = {'11', '12', '21', '22'}
STANDARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'standard.json')
STANDARD_CHARS = ['姬子', '瓦尔特', '布洛妮娅', '杰帕德', '克拉拉', '彦卿', '白露']


def load_pool_names():
    try:
        with open(STANDARD_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_pool_names(d):
    with open(STANDARD_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def chosen_names(doc):
    """这个账号在「星缘相邀」里选的角色：每个账号各存在自己的 data/<uid>.json 里；没设过就用 standard.json 里的默认。"""
    if '星缘相邀' in doc:
        return list(doc['星缘相邀'])
    return list(load_pool_names().get('星缘相邀', []))


def standard_names(doc):
    """会歪出来的五星 = 常驻角色 + 这个账号星缘相邀自选的 + 常驻光锥 + 常驻池里实际出过的五星。"""
    d = load_pool_names()
    names = set(STANDARD_CHARS) | set(d.get('常驻角色', [])) | set(chosen_names(doc)) | set(d.get('光锥', []))
    names |= {r['name'] for r in doc['records'] if r['gacha_type'] == '1' and r['rank_type'] == '5'}
    return names


def banner_up(records):
    """每个限定卡池（gacha_id）的 UP：出过不止一种五星时，取出得最多的那个；判断不了的不放进来。"""
    by = {}
    for r in records:
        if r['rank_type'] == '5' and r['gacha_type'] in LIMITED and r.get('gacha_id'):    # 有的记录没有 gacha_id，没法按卡池分
            by.setdefault(r['gacha_id'], Counter())[r['name']] += 1
    up = {}
    for gid, c in by.items():
        top = c.most_common(2)
        if len(top) == 2 and top[0][1] > top[1][1]:
            up[gid] = top[0][0]
    return up


@dataclass
class Five:
    name: str
    item_id: str
    item_type: str
    time: str            # 截图导入的早期记录没有时间，为空
    pulls: object        # 抽数；None 表示不知道
    uncertain: bool      # 记录起点之前可能还有垫的抽数，真实抽数 ≥ pulls
    result: str          # 限定池：'不歪' / '歪' / '大保底' / '限定'（不知道当时是小保底还是大保底）；常驻池：''
    gacha_type: str = ''
    key: str = ''        # 手动标记歪/不歪时用的编号：官方记录用记录 id，截图导入的用 L<卡池>-<序号>
    manual: bool = False # 歪没歪是用户手动标的


@dataclass
class PoolStats:
    gacha_type: str
    name: str
    hard_pity: int
    limited: bool
    total: int = 0
    early: int = 0               # 其中来自截图的早期抽数
    fives: list = field(default_factory=list)
    pity: int = 0                # 距上个五星已垫
    pity_uncertain: bool = True  # 还没出过五星时，垫的抽数可能更多
    guaranteed: object = None    # True 下个必是限定 / False 小保底 / None 不确定
    first_time: str = ''

    @property
    def avg(self):
        known = [f.pulls for f in self.fives if not f.uncertain and f.pulls]
        return sum(known) / len(known) if known else None

    @property
    def not_off(self):
        return sum(f.result == '不歪' for f in self.fives)

    @property
    def off(self):
        return sum(f.result == '歪' for f in self.fives)


def _judge(s, is_off):
    if not s.limited:
        return ''
    if is_off:
        result = '歪'                   # 只有小保底才可能歪
    elif s.guaranteed is True:
        result = '大保底'
    elif s.guaranteed is False:
        result = '不歪'
    else:
        result = '限定'                 # 记录起点之前的情况未知，不计入不歪率
    s.guaranteed = is_off
    return result


def pool_stats(records, gacha_type, standard, legacy=None, complete=False, up=None, overrides=None):
    name, hard, _ = POOLS[gacha_type]
    up, overrides = up or {}, overrides or {}
    s = PoolStats(gacha_type, name, hard, gacha_type in LIMITED)
    if complete:
        s.guaranteed = False            # 有完整历史时，第一个五星一定是小保底
    seen5 = complete
    since5 = 0

    def is_off(key, auto):
        return overrides[key] == '歪' if key in overrides else auto

    if legacy:
        for i, f in enumerate(legacy.get('fives', [])):
            key = f'L{gacha_type}-{i}'
            s.fives.append(Five(f['name'], f['item_id'], f['item_type'], '', f.get('pulls'), False,
                                _judge(s, is_off(key, f.get('off', False))), gacha_type, key, key in overrides))
        s.early = legacy.get('total') or sum(f.get('pulls') or 0 for f in legacy.get('fives', [])) + legacy.get('tail', 0)
        since5 = legacy.get('tail', 0)
        seen5 = seen5 or bool(legacy.get('fives'))
    recs = [r for r in records if r['gacha_type'] == gacha_type]
    s.total = s.early + len(recs)
    if recs:
        s.first_time = recs[0]['time']
    for r in recs:
        since5 += 1
        if r['rank_type'] == '5':
            gid = r.get('gacha_id')
            auto = r['name'] != up[gid] if gid in up else r['name'] in standard
            s.fives.append(Five(r['name'], r['item_id'], r['item_type'], r['time'], since5, not seen5,
                                _judge(s, is_off(r['id'], auto)), gacha_type, r['id'], r['id'] in overrides))
            seen5 = True
            since5 = 0
    s.pity = since5
    s.pity_uncertain = not seen5 and bool(recs)
    return s


def all_stats(doc):
    records = doc['records']
    legacy = doc.get('legacy') or {}
    pools = legacy.get('pools', {})
    standard = standard_names(doc)
    up = banner_up(records)
    overrides = doc.get('overrides') or {}
    return {gt: pool_stats(records, gt, standard, pools.get(gt), legacy.get('complete', False), up, overrides)
            for gt in POOLS}
