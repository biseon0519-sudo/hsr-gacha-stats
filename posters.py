# 两种五星展示：头像墙（小黑盒那样的方形头像 + 抽数 + 歪章）和海报模式（iPhone 后台那样横向叠放的大卡片）
import math
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPainterPath, QLinearGradient, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QToolTip
from qfluentwidgets import isDarkTheme, qconfig
from images import images
from gacha_api import POOLS

FONT = 'Microsoft YaHei UI'
SHORT = {'11': '角色', '12': '光锥', '1': '常驻', '21': '角色联动', '22': '光锥联动', '2': '新手'}
STAMP = QColor('#d63c32')


def ink(alpha=1.0):
    c = QColor(255, 255, 255) if isDarkTheme() else QColor(0, 0, 0)
    c.setAlphaF(alpha)
    return c


def luck_color(pulls, hard):
    """按占保底的比例上色：早出绿、中间黄、贴着保底红。"""
    if not pulls:
        return ink(0.5)
    r = pulls / hard
    if r <= 0.55:
        return QColor('#3fb26b') if isDarkTheme() else QColor('#23874a')
    if r <= 0.8:
        return QColor('#e6ac3c') if isDarkTheme() else QColor('#c27c12')
    return QColor('#ec6a5e') if isDarkTheme() else QColor('#c73a2e')


def pulls_text(f):
    if f.pulls is None:
        return '?'
    return ('≥' if f.uncertain else '') + str(f.pulls)


def describe(f, hard):
    when = f.time[:16] if f.time else '无时间数据'
    lines = [f'{f.name}　{SHORT.get(f.gacha_type, "")}', when]
    lines.append(f'第 {f.pulls} 抽出金（保底 {hard}）' if f.pulls else '抽数未知')
    if f.uncertain:
        lines.append('这是记录里最早的五星，再往前可能还有垫的抽数，所以实际 ≥ 这个数')
    lines.append({'歪': '小保底歪了，下一个五星必是限定', '大保底': '上一个歪了，这个是大保底',
                  '不歪': '小保底不歪', '限定': '不知道当时是小保底还是大保底'}.get(f.result, '')
                 + ('（你手动标的）' if f.manual else ''))
    if f.gacha_type in ('11', '12', '21', '22'):
        lines.append('判断不对的话，右键可以手动改')
    return '\n'.join(l for l in lines if l)


def draw_cover(p, pm, rect, align_top=False):
    """把图片按“铺满并居中裁切”的方式画进 rect。"""
    if pm is None or pm.isNull():
        return
    s = max(rect.width() / pm.width(), rect.height() / pm.height())
    w, h = rect.width() / s, rect.height() / s
    x = (pm.width() - w) / 2
    y = 0 if align_top else (pm.height() - h) / 2
    p.drawPixmap(rect, pm, QRectF(x, y, w, h))


def draw_stamp(p, center, r):
    """红色印章“歪”。"""
    p.save()
    p.translate(center); p.rotate(-14)
    p.setBrush(QColor(255, 255, 255, 40)); p.setPen(QPen(STAMP, max(2, r * 0.12)))
    p.drawEllipse(QPointF(0, 0), r, r)
    p.setPen(QPen(STAMP, max(1, r * 0.05)))
    p.drawEllipse(QPointF(0, 0), r * 0.78, r * 0.78)
    f = QFont(FONT); f.setPixelSize(int(r * 1.05)); f.setBold(True)
    p.setFont(f); p.setPen(STAMP)
    p.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignCenter, '歪')
    p.restore()


def card_bg(p, rect, radius):
    """五星卡片的金棕色底。"""
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, QColor('#8d6a4a')); g.setColorAt(1, QColor('#c09060'))
    path = QPainterPath(); path.addRoundedRect(rect, radius, radius)
    p.fillPath(path, g)
    return path


def draw_tile(p, rect, img_h, f, text, color, font, radius=10):
    """头像墙的一格：金棕底 + 头像（f 为 None 时画“?”）+ 下方浅色条上的数字。"""
    img = QRectF(rect.x(), rect.y(), rect.width(), img_h)
    label = QRectF(rect.x(), rect.y() + img_h, rect.width(), rect.height() - img_h)
    path = card_bg(p, rect, radius)
    p.save(); p.setClipPath(path)
    if f is None:
        q = QFont(FONT); q.setPixelSize(int(img_h * 0.55)); q.setBold(True)
        p.setFont(q); p.setPen(QColor(255, 255, 255, 230)); p.drawText(img, Qt.AlignCenter, '?')
    else:
        draw_cover(p, images().get('avatar', f.item_id, f.name), img)
    p.fillRect(label, QColor('#3a3631') if isDarkTheme() else QColor('#f4efe6'))
    p.restore()
    p.setFont(font); p.setPen(color)
    p.drawText(label, Qt.AlignCenter, text)


class _Themed(QWidget):
    markRequested = Signal(object, object)    # 右键某个五星：(Five, 鼠标的屏幕坐标)，由主窗口弹菜单

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        qconfig.themeChanged.connect(self.update)
        images().updated.connect(self.update)


class AvatarWall(_Themed):
    """小黑盒那样的头像墙：最新的在最前，第一格是“?”+ 距上个五星已抽多少。"""
    W, IMG, LABEL, GAP, PAD = 88, 88, 30, 12, 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fives, self.hard, self.pity = [], 90, None
        self.cards = []

    def set_data(self, fives, hard, pity=None):
        self.fives, self.hard, self.pity = list(reversed(fives)), hard, pity
        self._relayout()
        self.update()

    def _cols(self):
        return max(1, int((self.width() - self.PAD + self.GAP) // (self.W + self.GAP)))

    def _relayout(self):
        n = len(self.fives) + (self.pity is not None)
        rows = max(1, math.ceil(n / self._cols()))
        self.setMinimumHeight(self.PAD + rows * (self.IMG + self.LABEL + self.GAP))

    def resizeEvent(self, e):
        self._relayout()
        super().resizeEvent(e)

    def _rect(self, i):
        cols = self._cols()
        used = cols * (self.W + self.GAP) - self.GAP
        x0 = max(self.PAD / 2, (self.width() - used) / 2)
        r, c = divmod(i, cols)
        return QRectF(x0 + c * (self.W + self.GAP), self.PAD + r * (self.IMG + self.LABEL + self.GAP), self.W, self.IMG + self.LABEL)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        if not self.fives and self.pity is None:
            p.setPen(ink(0.5)); p.drawText(self.rect(), Qt.AlignCenter, '这个池子还没有出过五星'); return
        num_font = QFont(FONT); num_font.setPixelSize(19); num_font.setBold(True)
        items = ([None] if self.pity is not None else []) + self.fives
        stamps = []
        for i, f in enumerate(items):
            rect = self._rect(i)
            if f is None:
                draw_tile(p, rect, self.IMG, None, str(self.pity), ink(0.75), num_font)
            else:
                draw_tile(p, rect, self.IMG, f, pulls_text(f), luck_color(f.pulls, self.hard), num_font)
            if f is not None and f.result == '歪':
                stamps.append(QPointF(rect.right() - 12, rect.y() + 12))
        for c in stamps:                  # 章最后盖，压在相邻卡片上面也不会被挡住
            draw_stamp(p, c, 19)

    def _hit(self, pos):
        n = len(self.fives) + (self.pity is not None)
        for i in range(n):
            if self._rect(i).contains(pos):
                return i - (self.pity is not None)
        return None

    def mouseMoveEvent(self, e):
        i = self._hit(e.position())
        if i is None:
            QToolTip.hideText()
        elif i < 0:
            QToolTip.showText(e.globalPosition().toPoint(), f'当前已抽 {self.pity} 抽', self)
        else:
            QToolTip.showText(e.globalPosition().toPoint(), describe(self.fives[i], self.hard), self)

    def contextMenuEvent(self, e):
        i = self._hit(e.pos())
        if i is not None and i >= 0:
            self.markRequested.emit(self.fives[i], e.globalPos())


class FiveTile(_Themed):
    """单独一格头像（总览里的新手跃迁卡片用）：头像 + 下方第几抽出的，数字用正文颜色。
    还没出五星时和头像墙第一格一样：黄底问号 + 已抽多少。"""
    IMG, LABEL = 58, 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f, self.hard, self.pity = None, 90, 0
        self.setFixedSize(self.IMG, self.IMG + self.LABEL)

    def set_data(self, f, hard, pity=0):
        self.f, self.hard, self.pity = f, hard, pity
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        font = QFont(FONT); font.setPixelSize(16); font.setBold(True)
        text = pulls_text(self.f) if self.f is not None else str(self.pity)
        draw_tile(p, QRectF(self.rect()), self.IMG, self.f, text, ink(), font, radius=8)

    def mouseMoveEvent(self, e):
        tip = describe(self.f, self.hard) if self.f is not None else f'还没出五星，已抽 {self.pity} 抽'
        QToolTip.showText(e.globalPosition().toPoint(), tip, self)


class PosterFlow(_Themed):
    """海报模式：正在看的卡片在正中间完整显示，和两边隔开一段；两边像 iPhone 后台那样一张压一张往外排，一直延伸到画面外。
    旧的在右边、新的在左边，打开时停在最新的一张。滚轮、拖动、方向键切换。"""
    focusChanged = Signal(int, int)       # 当前第几个、一共几个
    RATIO = 0.58                          # 卡片宽高比（images.POSTER_RATIO 按这个裁海报）
    GAP, SIDE = 28, 0.92                  # 中间卡片和两边的间距；两边卡片的缩放
    STEP = 0.30                           # 两边每往外一张，下面那张露出自己宽度的 30%

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.fives, self.pos = [], 0.0
        self._scaled = {}
        self._drag = None
        self.anim = QVariantAnimation(self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.setDuration(420)
        self.anim.valueChanged.connect(self._set_pos)
        self.setMinimumHeight(360)

    def set_data(self, fives):
        self.fives = list(fives)
        self.anim.stop()
        self._set_pos(float(max(0, len(self.fives) - 1)))

    def _set_pos(self, v):
        self.pos = float(v)
        self.update()
        if self.fives:
            self.focusChanged.emit(int(round(self.pos)) + 1, len(self.fives))

    def go(self, target):
        if not self.fives:
            return
        target = max(0.0, min(float(len(self.fives) - 1), float(target)))
        self.anim.stop()
        self.anim.setStartValue(self.pos); self.anim.setEndValue(target)
        self.anim.start()

    # ---------- 几何 ----------
    def _size(self):
        """中间卡片的宽高：按窗口高度定，窗口太窄时也别超过宽度的 45%。"""
        h = min(self.height() - 66, 720)
        w = min(h * self.RATIO, self.width() * 0.45)
        return w, w / self.RATIO

    def _place(self, d):
        """第 d 张（相对当前焦点）卡片的中心 x、缩放、遮暗程度。d < 0（更旧）在右边，d > 0 在左边。"""
        cw, ch = self._size()
        t = abs(d)
        near = cw / 2 + self.GAP + self.SIDE * cw / 2          # 两边第一张的中心离中间多远
        if t <= 1:                                 # 从中间滑到两边第一张的位置
            s = 1 + (self.SIDE - 1) * t
            off = t * near
            dim = 0.2 * t
        else:                                      # 再往外每张错开一段，压在里面那张下面，排到画面外
            s = self.SIDE
            off = near + (t - 1) * self.STEP * self.SIDE * cw
            dim = min(0.5, 0.2 + 0.1 * (t - 1))
        return self.width() / 2 + (off if d < 0 else -off), s, dim

    def _visible(self):
        """要画的卡片，从最外面往中间排（后画的压在上面）。"""
        lo = max(0, int(self.pos) - 6)
        hi = min(len(self.fives) - 1, int(math.ceil(self.pos)) + 6)
        return sorted(range(lo, hi + 1), key=lambda i: -abs(i - self.pos))

    def _card_rect(self, i):
        cw, ch = self._size()
        x, s, _ = self._place(i - self.pos)
        top = 50 + max(0, (self.height() - 60 - ch) / 2) + ch * (1 - s) / 2
        return QRectF(x - cw * s / 2, top, cw * s, ch * s), s

    # ---------- 绘制 ----------
    def _poster(self, f, w, h):
        pm = images().get('poster', f.item_id, f.name)
        if pm is None:
            pm = images().get('avatar', f.item_id, f.name)
        if pm is None:
            return None
        key = (pm.cacheKey(), int(w), int(h))
        out = self._scaled.get(key)
        if out is None:
            ratio = self.devicePixelRatioF()
            out = QPixmap(int(w * ratio), int(h * ratio)); out.setDevicePixelRatio(ratio)
            out.fill(Qt.transparent)
            q = QPainter(out); q.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            draw_cover(q, pm, QRectF(0, 0, w, h), align_top=True)
            q.end()
            if len(self._scaled) > 80:
                self._scaled.clear()
            self._scaled[key] = out
        return out

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        if not self.fives:
            p.setPen(ink(0.5)); p.drawText(self.rect(), Qt.AlignCenter, '还没有五星'); return
        cw, ch = self._size()
        for i in self._visible():
            f = self.fives[i]
            rect, s = self._card_rect(i)
            _, _, dim = self._place(i - self.pos)
            hard = POOLS.get(f.gacha_type, ('', 90))[1]
            # 中间那张的上方：小头像 + 名字（像 iPhone 后台的 App 图标和名字），滑走时淡出
            fade = 1 - min(1.0, abs(i - self.pos))
            if fade > 0:
                p.save(); p.setOpacity(fade)
                av = images().get('avatar', f.item_id, f.name)
                icon = QRectF(rect.x() + 4, rect.y() - 40, 30, 30)
                if av is not None:
                    p.save(); clip = QPainterPath(); clip.addEllipse(icon); p.setClipPath(clip)
                    draw_cover(p, av, icon); p.restore()
                nf = QFont(FONT); nf.setPixelSize(15); nf.setBold(True); p.setFont(nf)
                p.setPen(ink(0.85))
                avail = int(rect.width() - 50)
                p.drawText(QRectF(icon.right() + 8, icon.y(), avail, 30), Qt.AlignVCenter | Qt.AlignLeft,
                           QFontMetrics(nf).elidedText(f.name, Qt.ElideRight, avail))
                p.restore()
            # 卡片阴影
            for k in range(6):
                sh = QPainterPath(); sh.addRoundedRect(rect.adjusted(-k, -k + 4, k, k + 6), 22 + k, 22 + k)
                p.fillPath(sh, QColor(0, 0, 0, 10))
            # 卡片本体
            path = QPainterPath(); path.addRoundedRect(rect, 22 * s, 22 * s)
            g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            g.setColorAt(0, QColor('#2b2f4a')); g.setColorAt(1, QColor('#5a4632'))
            p.fillPath(path, g)
            p.save(); p.setClipPath(path)
            pm = self._poster(f, cw, ch)
            if pm is not None:
                p.drawPixmap(rect, pm, QRectF(0, 0, pm.width(), pm.height()))
            # 底部渐变压暗，放文字
            bottom = QRectF(rect.x(), rect.bottom() - rect.height() * 0.34, rect.width(), rect.height() * 0.34)
            bg = QLinearGradient(bottom.topLeft(), bottom.bottomLeft())
            bg.setColorAt(0, QColor(0, 0, 0, 0)); bg.setColorAt(1, QColor(0, 0, 0, 200))
            p.fillRect(bottom, bg)
            pad = 18 * s
            big = QFont(FONT); big.setPixelSize(int(26 * s)); big.setBold(True)
            p.setFont(big); p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(rect.x() + pad, rect.bottom() - 84 * s, rect.width() - 2 * pad, 36 * s),
                       Qt.AlignLeft | Qt.AlignVCenter, QFontMetrics(big).elidedText(f.name, Qt.ElideRight, int(rect.width() - 2 * pad)))
            small = QFont(FONT); small.setPixelSize(int(13 * s)); p.setFont(small); p.setPen(QColor(255, 255, 255, 190))
            line = SHORT.get(f.gacha_type, '') + (f' · {f.time[:10]}' if f.time else '')    # 没有时间就只写卡池
            p.drawText(QRectF(rect.x() + pad, rect.bottom() - 46 * s, rect.width() - 2 * pad, 24 * s),
                       Qt.AlignLeft | Qt.AlignVCenter, line)
            # 右下角：抽数 + “抽”，和卡池那行底边对齐；歪没歪只看右上角的章
            base = rect.bottom() - 28 * s
            unit = QFont(FONT); unit.setPixelSize(int(12 * s))
            num = QFont(FONT); num.setPixelSize(int(30 * s)); num.setBold(True)
            ux = rect.right() - pad - QFontMetrics(unit).horizontalAdvance('抽')
            p.setFont(unit); p.setPen(QColor(255, 255, 255, 190))
            p.drawText(QPointF(ux, base), '抽')
            c = QColor(luck_color(f.pulls, hard) if f.pulls else QColor(255, 255, 255)).lighter(125)
            p.setFont(num); p.setPen(c)
            p.drawText(QPointF(ux - 3 * s - QFontMetrics(num).horizontalAdvance(pulls_text(f)), base), pulls_text(f))
            if dim:
                p.fillPath(path, QColor(0, 0, 0, int(255 * dim)))
            p.restore()
            if f.result == '歪':
                draw_stamp(p, QPointF(rect.right() - 40 * s, rect.y() + 42 * s), 30 * s)

    # ---------- 交互 ----------
    def wheelEvent(self, e):
        d = e.angleDelta()
        delta = d.x() if abs(d.x()) > abs(d.y()) else d.y()
        if not delta:
            return
        base = self.anim.endValue() if self.anim.state() == QVariantAnimation.Running else self.pos
        self.go(round(base) + (-1 if delta > 0 else 1))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Left:                 # 左边是更新的
            self.go(round(self.pos) + 1)
        elif e.key() == Qt.Key_Right:
            self.go(round(self.pos) - 1)
        elif e.key() == Qt.Key_Home:
            self.go(0)
        elif e.key() == Qt.Key_End:
            self.go(len(self.fives) - 1)
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.anim.stop()
            self._drag = (e.position().x(), self.pos, False)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            x0, p0, moved = self._drag
            dx = e.position().x() - x0
            if abs(dx) > 4:
                moved = True
            cw, _ = self._size()
            self._drag = (x0, p0, moved)
            if moved:
                self._set_pos(max(0.0, min(len(self.fives) - 1.0, p0 + dx / (cw * 0.5))))
            return
        hit = self._hit(e.position())
        if hit is None:
            QToolTip.hideText()
        else:
            f = self.fives[hit]
            QToolTip.showText(e.globalPosition().toPoint(), describe(f, POOLS.get(f.gacha_type, ('', 90))[1]), self)

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        _, _, moved = self._drag
        self._drag = None
        if moved:
            self.go(round(self.pos))
        else:
            hit = self._hit(e.position())
            if hit is not None:
                self.go(hit)

    def contextMenuEvent(self, e):
        hit = self._hit(e.pos())
        if hit is not None:
            self.markRequested.emit(self.fives[hit], e.globalPos())

    def _hit(self, pos):
        for i in reversed(self._visible()):       # 后画的在上面，先查
            rect, _ = self._card_rect(i)
            if rect.contains(pos):
                return i
        return None
