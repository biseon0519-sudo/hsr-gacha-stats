# 找抽卡链接（读游戏缓存）+ 从米哈游接口拉取记录
import os, re, json, time, glob, functools, urllib.request, urllib.parse

# 卡池：gacha_type -> (名称, 保底抽数, 接口)
POOLS = {
    '11': ('角色跃迁',     90, 'getGachaLog'),
    '12': ('光锥跃迁',     80, 'getGachaLog'),
    '1':  ('常驻跃迁',     90, 'getGachaLog'),
    '21': ('角色联动跃迁', 90, 'getLdGachaLog'),
    '22': ('光锥联动跃迁', 80, 'getLdGachaLog'),
    '2':  ('新手跃迁',     50, 'getGachaLog'),
}

LOG_DIRS = [os.path.expandvars(r'%USERPROFILE%\AppData\LocalLow\miHoYo\崩坏：星穹铁道'),
            os.path.expandvars(r'%USERPROFILE%\AppData\LocalLow\Cognosphere\Star Rail')]
URL_RE = re.compile(rb'https://[^\x00\s"<>]+?/get(?:Ld)?GachaLog\?[^\x00\s"<>]+')

@functools.cache
def _opener():
    """米哈游是国内服务器，走代理反而连不上，所以一律直连。用到时才建（建的时候要加载 HTTPS 证书，启动时省下这点时间）。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class GachaError(Exception):
    pass


def game_data_dirs():
    """从游戏日志里找 StarRail_Data 目录，新日志优先。"""
    found = []
    for d in LOG_DIRS:
        for name in ('Player.log', 'Player-prev.log'):
            try:
                text = open(os.path.join(d, name), encoding='utf-8', errors='ignore').read()
            except OSError:
                continue
            for m in re.findall(r'([A-Za-z]:[/\\][^\r\n:"]*?StarRail_Data)', text):
                p = os.path.normpath(m)
                if p not in found and os.path.isdir(p):
                    found.append(p)
    return found


def find_url_in_cache():
    """在游戏网页缓存里找最近一次打开跃迁记录时留下的链接。找不到返回 None。"""
    caches = []
    for d in game_data_dirs():
        caches += glob.glob(os.path.join(d, 'webCaches', '*', 'Cache', 'Cache_Data', 'data_2'))
    for f in sorted(caches, key=os.path.getmtime, reverse=True):
        try:
            data = open(f, 'rb').read()
        except OSError:
            continue
        urls = [u for u in URL_RE.findall(data) if b'authkey=' in u]
        if urls:
            return urls[-1].decode('utf-8', 'ignore')
    return None


def check_url(text):
    """从粘贴的内容里挑出跃迁记录链接：可以只是链接，也可以是一整段命令输出或聊天记录。"""
    m = re.search(r'https://[^\s"\'<>]+?/get(?:Ld)?GachaLog\?[^\s"\'<>]*authkey=[^\s"\'<>]+', text or '')
    if m is None:
        raise GachaError('没在粘贴的内容里找到跃迁记录链接：链接应该以 https:// 开头，并且包含 getGachaLog 和 authkey')
    return m.group(0)


def _get(base, query, path, gacha_type, end_id):
    q = dict(query, gacha_type=gacha_type, page='1', size='20', end_id=end_id)
    url = urllib.parse.urlunsplit((base.scheme, base.netloc, path, urllib.parse.urlencode(q), ''))
    for attempt in range(6):
        try:
            with _opener().open(url, timeout=15) as r:
                resp = json.load(r)
        except Exception as e:
            if attempt == 5:
                raise GachaError(f'连不上米哈游服务器：{e}')
            time.sleep(1 + attempt); continue
        code = resp.get('retcode')
        if code == 0 and resp.get('data') is not None:
            return resp['data']
        if code == -101:
            raise GachaError('链接已过期（大约一天有效）。请在游戏里重新打开一次「跃迁 → 查看详情」，再点更新')
        if code == -100:
            raise GachaError('链接无效，请重新在游戏里打开一次跃迁记录')
        time.sleep(1 + attempt)        # 多半是访问太频繁（-110），歇一下再试
    raise GachaError(f'接口一直返回错误：{resp.get("message")}（{code}），请稍后再试')


def fetch(url, known_ids=lambda uid: set(), progress=lambda text: None):
    """拉取全部卡池。遇到本地已有的记录就停（增量更新）。返回 (uid, 时区, 记录列表)。"""
    base = urllib.parse.urlsplit(check_url(url))
    query = {k: v for k, v in urllib.parse.parse_qsl(base.query) if k not in ('gacha_type', 'page', 'size', 'end_id')}
    query.setdefault('lang', 'zh-cn')
    prefix = base.path.rsplit('/', 1)[0]
    uid, tz, out = None, 8, []
    for gt, (name, _, api) in POOLS.items():
        end_id, n, known = '0', 0, None
        while True:
            data = _get(base, query, f'{prefix}/{api}', gt, end_id)
            tz = data.get('region_time_zone', tz)
            lst = data.get('list') or []
            if not lst:
                break
            if uid is None:
                uid = lst[0]['uid']
            if known is None:
                known = known_ids(uid)
            new = [r for r in lst if r['id'] not in known]
            out += new; n += len(new)
            progress(f'{name}：新增 {n} 条')
            if len(new) < len(lst):
                break
            end_id = lst[-1]['id']
            time.sleep(0.3)
    if uid is None:
        raise GachaError('链接有效，但这个账号没有任何跃迁记录')
    return uid, tz, out
