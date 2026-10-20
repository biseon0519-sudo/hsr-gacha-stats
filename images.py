# 角色/光锥图片：自动下载带背景的完整立绘（不是抠图版），放在 图片/ 下；
#   角色头像：完整立绘来自 enka.network（游戏里的 AvatarDrawCard）。StarRailRes 里的方形头像正好是从这张立绘上裁出来的（抠了背景），
#         所以在立绘里找到它的位置，按同样范围从立绘上裁，就是带背景的头像。
#   角色海报：BWIKI 上的「<名字>立绘2」是官方角色公开海报（横版、完整背景，一侧印着名字），找到人物后竖着裁一条，避开文字；
#         没有的话从上面那张立绘以头为中心裁，透明处垫底色。
#   光锥：StarRailRes 的 light_cone_portrait 本来就是带背景的卡面，去掉银边后裁头像和海报。
#   下载不到完整立绘时退回抠图版。
# 用户放在 图片/自定义/ 里的同名图片优先（“真珠.jpg” 换海报，“真珠_头像.png” 换头像）
import os, json, time, threading, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PySide6.QtCore import QObject, Signal, Qt, QRect
from PySide6.QtGui import QPixmap, QImage, QPainter, QTransform, QColor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '图片')
AUTO = {'avatar': os.path.join(ROOT, '头像'), 'poster': os.path.join(ROOT, '海报')}
CUSTOM = os.path.join(ROOT, '自定义')
EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
STYLE = 'full-art-5'        # 自动下载的图的版本；和 图片/头像/.style 里记的不一样时，清掉旧图重新下
MIRRORS = ('https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/',
           'https://cdn.jsdelivr.net/gh/Mar-7th/StarRailRes@master/')
DRAWCARD = 'https://enka.network/ui/hsr/SpriteOutput/AvatarDrawCard/{}.png'
BWIKI = 'https://wiki.biligame.com/sr/api.php?action=query&prop=imageinfo&iiprop=url&format=json&titles='
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
POSTER_RATIO = 0.58         # 海报卡片的宽高比，和 posters.PosterFlow.RATIO 一致
MATCH_OK = 0.8              # 裁出来的头像和抠图版的相似度低于这个数，算没找到
README = """把图片放在这个文件夹里，就能替换工具里的角色图（重开工具或点一下“更新记录”后生效）：

  真珠.jpg        → 换掉「海报模式」里真珠的海报
  真珠_头像.png   → 换掉五星记录里真珠的方形头像

文件名就是游戏里的名字（光锥也一样，比如“爱如此刻永恒.jpg”），支持 png / jpg / webp。
海报会自动居中裁切铺满卡片，竖图效果最好；头像建议用正方形。
自动下载的图在旁边的「头像」「海报」文件夹里，删掉会重新下载。
"""


_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_bwiki_lock = threading.Lock()


def _read(url, direct=False):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with (_direct.open(req, timeout=60) if direct else urllib.request.urlopen(req, timeout=60)) as r:
        return r.read()


def _fetch(src, direct=False):
    """下载一张图；src 是完整网址，或 StarRailRes 里的相对路径（GitHub 走系统代理，连不上再试 jsDelivr）。
    direct：不走代理（BWIKI 会拦代理过来的请求）。"""
    for url in ([src] if src.startswith('http') else [m + src for m in MIRRORS]):
        try:
            img = QImage.fromData(_read(url, direct))
            if not img.isNull():
                return img
        except Exception:
            continue
    return None


_wanted = set()             # 等着找公开海报的角色名，攒起来一次查
_reveal_urls = {}           # 名字 → 图片地址；None 表示 BWIKI 上没有


def _reveal_url(name):
    """BWIKI 上「<名字>立绘2」（官方角色公开海报）的地址，没有返回 None；查询失败（比如被防刷拦了）抛异常。
    BWIKI 请求多了会被拦，所以一次把等着的角色都查掉（一次最多 50 个文件名，png/jpg 各试一个），查过的记住。"""
    with _bwiki_lock:
        if name not in _reveal_urls:
            names = [name] + [n for n in sorted(_wanted) if n != name and n not in _reveal_urls][:24]
            titles = '|'.join(f'文件:{n}立绘2.{ext}' for n in names for ext in ('png', 'jpg'))
            data = json.loads(_read(BWIKI + urllib.parse.quote(titles), direct=True))
            found = {}
            for page in data['query']['pages'].values():
                if page.get('imageinfo'):
                    found[page['title'].split(':', 1)[1].rsplit('立绘2.', 1)[0]] = page['imageinfo'][0]['url']
            for n in names:
                _reveal_urls[n] = found.get(n)
                _wanted.discard(n)
            time.sleep(1)
        return _reveal_urls[name]


def _arr(img):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()]
    return a.astype(np.float32)


def _search(d, f, rots, sides, xs, ys, rng, samples):
    """d：缩小 f 倍的立绘；rots：{角度: (转过这个角度的头像, 外框比原来大多少)}。
    试每个角度、边长、位置，比对头像不透明处的颜色。xs/ys 是头像中心的范围。
    返回 (误差, 角度, 头像边长, 中心 x, 中心 y)，都按原图像素算。"""
    h, w = d.shape[:2]
    best = (1e18, 0, 0, 0, 0)
    for ang, (rot, grow) in rots.items():
        for side in sides:
            k = max(4, round(side * grow / f))
            t = _arr(rot.scaled(k, k, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            ty, tx = np.nonzero(t[..., 3] > 220)
            if len(ty) < 10:
                continue
            pick = rng.choice(len(ty), min(samples, len(ty)), replace=False)
            ty, tx = ty[pick], tx[pick]
            tv = t[ty, tx, :3]
            x0, x1 = max(0, round(xs[0] / f - k / 2)), min(w - k, round(xs[1] / f - k / 2))
            y0, y1 = max(0, round(ys[0] / f - k / 2)), min(h - k, round(ys[1] / f - k / 2))
            if x1 < x0 or y1 < y0:
                continue
            px, py = (g.ravel() for g in np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1)))
            for c in range(0, len(px), 8192):              # 分块算，免得一次占太多内存
                cx, cy = px[c:c + 8192], py[c:c + 8192]
                err = np.abs(d[cy[:, None] + ty, cx[:, None] + tx] - tv).mean(axis=(1, 2))
                i = int(err.argmin())
                if err[i] < best[0]:
                    best = (float(err[i]), ang, side, (cx[i] + k / 2) * f, (cy[i] + k / 2) * f)
    return best


def locate_icon(art, icon):
    """找出抠图版头像在完整立绘里的位置。游戏的方形头像是把立绘转正一点再裁的（大黑塔转了 30° 左右），
    所以连角度一起找：先缩小粗找，再逐级放大细找。返回 (中心 x, 中心 y, 边长, 角度)。
    人物在立绘里很小时头像边长不到 160，缩小 16 倍就认不出了，所以小尺寸另外用 8 倍找。"""
    rng = np.random.default_rng(0)
    small = {f: _arr(art.scaled(art.width() // f, art.height() // f, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))[..., :3]
             for f in (16, 8, 4, 1)}

    def rots(angles):
        out = {}
        for a in angles:
            r = icon.transformed(QTransform().rotate(a), Qt.SmoothTransformation)
            out[a] = (r, r.width() / icon.width())
        return out

    whole = (0, art.width()), (0, art.height())
    coarse = rots(range(-45, 46, 15))
    b = min(_search(small[16], 16, coarse, range(160, 1600, 48), *whole, rng, 200),
            _search(small[8], 8, coarse, range(80, 161, 16), *whole, rng, 200))
    for f, span, step, astep in ((4, 64, 8, 4), (1, 8, 2, 1)):
        _, a, s, cx, cy = b
        b = _search(small[f], f, rots(range(a - 3 * astep, a + 3 * astep + 1, astep)),
                    range(max(16, s - 4 * step), s + 4 * step + 1, step), (cx - span, cx + span), (cy - span, cy + span), rng, 400)
    _, a, s, cx, cy = b
    return cx, cy, s, a


def upright_crop(art, cx, cy, side, angle):
    """从立绘上裁出以 (cx, cy) 为中心、转回 angle 度的正方形。"""
    out = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    p.translate(side / 2, side / 2); p.rotate(-angle); p.translate(-cx, -cy)
    p.drawImage(0, 0, art)
    p.end()
    return out


def similarity(crop, icon):
    """裁出来的头像和抠图版头像像不像：头像不透明处灰度的相关系数，1 是完全一样。"""
    a = _arr(crop.scaled(128, 128, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    t = _arr(icon.scaled(128, 128, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    m = t[..., 3] > 220
    ga, gt = a[..., :3].mean(2)[m], t[..., :3].mean(2)[m]
    return float(((ga - ga.mean()) * (gt - gt.mean())).mean() / (ga.std() * gt.std() + 1e-6))


def poster_rect(art, head):
    """竖版海报的裁切范围：以头为中心，尽量大，但别裁进立绘四周的透明边。
    有的立绘背景只画了人物周围一圈（真珠、知更鸟•晴歌），找不到不透明的大块，就放宽，透明处由 with_backdrop 垫底。"""
    small = art.scaled(256, 256, Qt.KeepAspectRatio, Qt.FastTransformation)
    alpha = _arr(small)[..., 3] > 200
    sx, sy = art.width() / small.width(), art.height() / small.height()
    cx, top = head.center().x(), head.y() - head.height() * 0.6

    def rect(hh):
        ww = hh * POSTER_RATIO
        return min(max(0, cx - ww / 2), art.width() - ww), min(max(0, top), art.height() - hh), ww, hh

    for need, lowest in ((0.997, 0.5), (0.85, 0.5)):
        for hh in np.linspace(art.height(), art.height() * lowest, 30):
            x, y, ww, hh = rect(hh)
            a = alpha[int(y / sy):int((y + hh) / sy), int(x / sx):int((x + ww) / sx)]
            if a.size and a.mean() > need:
                return QRect(int(x), int(y), int(ww), int(hh))
    return QRect(*(int(v) for v in rect(art.height() * 0.6)))


def with_backdrop(img):
    """透明的地方垫一层用这张图自己的颜色晕开的底（很模糊的放大版，压在平均色上），画面铺满、不露抠图边。"""
    a = _arr(img.scaled(64, 64, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    w = a[..., 3:] / 255
    avg = (a[..., :3] * w).sum((0, 1)) / max(w.sum(), 1)
    out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(QColor(*(int(v) for v in avg * 0.8)))
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    blur = img
    for s in (24, 8):                   # 先缩到很小再放大，就是一层很软的色块
        blur = blur.scaled(s, max(1, round(s * img.height() / img.width())), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    p.setOpacity(0.9)
    p.drawImage(out.rect(), blur.scaled(64, max(1, round(64 * img.height() / img.width())), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    p.setOpacity(1)
    p.drawImage(0, 0, img)
    p.end()
    return out


def _opaque_rect(img):
    """抠图立绘四周是大片透明，裁到有内容的范围。"""
    small = img.scaled(256, 256, Qt.KeepAspectRatio, Qt.FastTransformation)
    ys, xs = np.nonzero(_arr(small)[..., 3] > 40)
    if not len(xs):
        return img.rect()
    sx, sy = img.width() / small.width(), img.height() / small.height()
    return QRect(int(xs.min() * sx), int(ys.min() * sy), int((xs.max() - xs.min() + 1) * sx), int((ys.max() - ys.min() + 1) * sy))


class _MatchCache:
    """头像在立绘里的位置找一次要十几秒，记在 图片/头像/位置.json，以后重新生成图片时直接用。
    键是 item_id（在 enka 立绘里的位置）或 item_id@poster（在 BWIKI 公开海报里的位置）。
    '@retry' 里是这次没连上 BWIKI、先用了备用海报的 item，下次打开工具再试。"""

    def __init__(self):
        self.file = os.path.join(AUTO['avatar'], '位置.json')
        self.lock = threading.Lock()
        try:
            with open(self.file, encoding='utf-8') as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def get(self, item_id):
        v = self.data.get(item_id)
        return tuple(v) if v else None

    def put(self, item_id, found):
        with self.lock:
            self.data[item_id] = list(found)
            self._save()

    def mark_retry(self, item_id, on):
        with self.lock:
            retry = set(self.data.get('@retry', []))
            retry.add(item_id) if on else retry.discard(item_id)
            self.data['@retry'] = sorted(retry)
            self._save()

    def _save(self):
        with open(self.file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f)


_matches = None


def _find(key, art, icon):
    """头像在 art 里的位置（先查缓存），对不上返回 None。"""
    found = _matches.get(key) or locate_icon(art, icon)
    if similarity(upright_crop(art, *found), icon) < MATCH_OK:
        return None
    _matches.put(key, found)
    return found


def _dilate(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def remove_text(crop, x, poster_found, art, art_found):
    """早期角色的公开海报在人物旁边印着台词。海报里的画和 enka 立绘是同一张，按两边找到的头像位置把立绘对齐叠到海报上，
    逐像素比较：海报上多出来的（文字）用立绘的像素补上。立绘透明的地方没法比，就保持原样。"""
    w, h = crop.width(), crop.height()
    warped = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    warped.fill(Qt.transparent)
    p = QPainter(warped)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    k = poster_found[2] / art_found[2]
    p.translate(poster_found[0] - x, poster_found[1]); p.rotate(poster_found[3] - art_found[3])
    p.scale(k, k); p.translate(-art_found[0], -art_found[1])
    p.drawImage(0, 0, art)
    p.end()
    a, b = _arr(crop), _arr(warped)
    solid = b[..., 3] > 230
    if not solid.any() or np.median(np.abs(a - b)[..., :3].mean(2)[solid]) > 12:     # 没对齐好就别动
        return crop
    text = _dilate((np.abs(a - b)[..., :3].mean(2) > 35) & solid, 3) & solid
    a[text] = b[text]
    out = np.ascontiguousarray(a.astype(np.uint8))
    return QImage(out.data, w, h, w * 4, QImage.Format_RGBA8888).copy()


def reveal_poster(item_id, name, icon, art=None, art_found=None):
    """从官方角色公开海报里竖着裁一条：整个高度，以人物的头为中心；有对齐好的 enka 立绘时顺便去掉海报上的文字。
    BWIKI 上没有或认不出人物返回 None；连不上（被拦、下载失败）抛异常，由调用方记下来下次重试。"""
    url = _reveal_url(name)
    if url is None:
        return None
    poster = _fetch(url, direct=True)
    if poster is None:
        raise OSError('公开海报下载失败')
    found = _find(f'{item_id}@poster', poster, icon)
    if found is None:
        return None
    h = poster.height()
    w = int(h * POSTER_RATIO)
    x = int(min(max(0, found[0] - w / 2), poster.width() - w))
    crop = poster.copy(x, 0, w, h)
    return remove_text(crop, x, found, art, art_found) if art_found is not None else crop


def make_images(item_id, name):
    """下载并裁好一个角色/光锥的 {'avatar': QImage, 'poster': QImage}；下载失败的那项缺省。"""
    if int(item_id) < 20000:
        art, icon = _fetch(DRAWCARD.format(item_id)), _fetch(f'icon/character/{item_id}.png')
        if art is not None and icon is not None:
            found = _find(item_id, art, icon)
            if found is not None:
                cx, cy, side, _ = found
                avatar = with_backdrop(upright_crop(art, *found))
                head = QRect(int(cx - side / 2), int(cy - side / 2), side, side)
            else:                       # 没对上：头像用抠图版，海报从立绘中间裁
                avatar, head = icon, QRect(art.width() // 2 - 100, art.height() // 3, 200, 200)
            try:
                poster, retry = reveal_poster(item_id, name, icon, art, found), False
            except Exception:
                poster, retry = None, True
            _matches.mark_retry(item_id, retry)
            return {'avatar': avatar, 'poster': poster or with_backdrop(art.copy(poster_rect(art, head)))}
        out = {'avatar': icon} if icon is not None else {}
        portrait = _fetch(f'image/character_portrait/{item_id}.png')
        if portrait is not None:
            out['poster'] = portrait.copy(portrait.rect().intersected(_opaque_rect(portrait)))
        return out
    card = _fetch(f'image/light_cone_portrait/{item_id}.png')
    if card is None:
        return {}
    inner = card.rect().adjusted(*(int(card.width() * k) for k in (0.035, 0.03, -0.035, -0.03)))   # 去掉银边
    side = inner.width()
    return {'avatar': card.copy(inner.x(), inner.y() + int((inner.height() - side) * 0.3), side, side),
            'poster': card.copy(inner)}


class ImageStore(QObject):
    updated = Signal()          # 有新图下载好了

    def __init__(self):
        super().__init__()
        for d in (*AUTO.values(), CUSTOM):
            os.makedirs(d, exist_ok=True)
        readme = os.path.join(CUSTOM, '说明.txt')
        if not os.path.exists(readme):
            with open(readme, 'w', encoding='utf-8') as f:
                f.write(README)
        self._upgrade()
        global _matches
        _matches = _MatchCache()
        for i in _matches.data.get('@retry', []):        # 上次没连上 BWIKI 的，删掉备用海报，用到时重新下
            try:
                os.remove(os.path.join(AUTO['poster'], f'{i}.png'))
            except OSError:
                pass
        self._cache = {}
        self._pending, self._failed = set(), set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(4)

    def _upgrade(self):
        mark = os.path.join(AUTO['avatar'], '.style')
        try:
            with open(mark, encoding='utf-8') as f:
                if f.read().strip() == STYLE:
                    return
        except OSError:
            pass
        for d in AUTO.values():
            for n in os.listdir(d):
                if n.endswith('.png'):
                    os.remove(os.path.join(d, n))
        with open(mark, 'w', encoding='utf-8') as f:
            f.write(STYLE)

    def path(self, kind, item_id, name):
        suffix = '_头像' if kind == 'avatar' else ''
        for ext in EXTS:
            p = os.path.join(CUSTOM, name + suffix + ext)
            if os.path.exists(p):
                return p
        p = os.path.join(AUTO[kind], f'{item_id}.png')
        return p if os.path.exists(p) else None

    def get(self, kind, item_id, name):
        """返回 QPixmap；还没有就排队下载、先返回 None。"""
        p = self.path(kind, item_id, name)
        if p is None:
            self.request([(kind, item_id, name)])
            return None
        key = (p, os.path.getmtime(p))
        pm = self._cache.get(key)
        if pm is None:
            pm = self._cache[key] = QPixmap(p)
        return pm

    def request(self, items):
        """items: [(kind, item_id, 名字)]。同一个 item 的头像和海报一起下载。"""
        names = {i: n for k, i, n in items if not os.path.exists(os.path.join(AUTO[k], f'{i}.png'))}
        with self._lock:
            new = set(names) - self._pending - self._failed
            self._pending |= new
        with _bwiki_lock:
            _wanted.update(names[i] for i in new if int(i) < 20000)
        for i in new:
            self._pool.submit(self._download, i, names[i])

    def _download(self, item_id, name):
        try:
            imgs = make_images(item_id, name)
        except Exception:
            imgs = {}
        with self._lock:
            self._pending.discard(item_id)
            if not imgs:
                self._failed.add(item_id)
        for kind, img in imgs.items():
            limit = 256 if kind == 'avatar' else 1200          # 原图 2048px，缩小再存，省空间也画得快
            if max(img.width(), img.height()) > limit:
                img = img.scaled(limit, limit, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img.save(os.path.join(AUTO[kind], f'{item_id}.png'))
        if imgs:
            self.updated.emit()


store = None


def images():
    global store
    if store is None:
        store = ImageStore()
    return store
