# 每月抽数柱状图：各卡池按颜色叠在一根柱子上，只算官方记录（截图导入的记录没有日期）。鼠标移上去看明细
# 月份多了放不下时左右滑动（拖动、触控板横向滑、Shift+滚轮，或点两边的箭头），打开时停在最近的月份
import math
from collections import Counter
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPainterPath
from PySide6.QtWidgets import QWidget, QToolTip
from qfluentwidgets import isDarkTheme, themeColor, qconfig
from gacha_api import POOLS
from posters import FONT, SHORT, ink


def pool_color(gt):
    # 用户要求沿用最早那版的配色：角色是系统主题色，光锥青色，常驻灰色
    return {'11': themeColor(), '12': QColor('#2ba6a0'), '1': QColor('#8a8f98'),
            '21': QColor('#d2691e'), '22': QColor('#c2185b'), '2': QColor('#7cb342')}.get(gt, QColor('#888'))


def nice_step(top):
    """纵轴刻度间隔：1、2、5 × 10 的幂，大约分 4 格。"""
    raw = max(top, 1) / 4
    k = 10 ** math.floor(math.log10(raw))
    return next(m * k for m in (1, 2, 5, 10) if m * k >= raw)


class MonthlyChart(QWidget):
    LEFT, RIGHT, TOP, BOTTOM = 44, 8, 46, 40
    BAND = 72                     # 每个月至少占这么宽，放不下就左右滑
    ARROW = 22                    # 两边“还有更多”箭头的点击范围

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(250)
        self.months = []          # [(年月 'YYYY-MM', 各卡池 Counter)]，没抽的月份也列出来
        self.order = []           # 有记录的卡池，从下往上叠的顺序
        self.hover = None
        self.off = 0.0            # 往左滑了多少像素；0 是最早的月份贴着左边
        self._drag = None
        self.anim = QVariantAnimation(self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic); self.anim.setDuration(320)
        self.anim.valueChanged.connect(self._set_off)
        qconfig.themeChanged.connect(self.update)

    def set_data(self, records):
        by = {}
        for r in records:
            by.setdefault(r['time'][:7], Counter())[r['gacha_type']] += 1
        self.months = []
        if by:
            y, m = map(int, min(by).split('-'))
            while True:
                ym = f'{y:04d}-{m:02d}'
                self.months.append((ym, by.get(ym, Counter())))
                if ym >= max(by):
                    break
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        self.order = [gt for gt in POOLS if any(c[gt] for _, c in self.months)]
        self.hover = None
        self.anim.stop()
        self.off = self._max_off()        # 停在最近的月份
        self.update()

    # ---------- 几何 ----------
    def _plot(self):
        return QRectF(self.LEFT, self.TOP, self.width() - self.LEFT - self.RIGHT, self.height() - self.TOP - self.BOTTOM)

    def _band_w(self):
        return max(self.BAND, self._plot().width() / max(1, len(self.months)))

    def _max_off(self):
        return max(0.0, self._band_w() * len(self.months) - self._plot().width())

    def _band(self, i):
        plot = self._plot()
        w = self._band_w()
        return QRectF(plot.x() + i * w - self.off, plot.y(), w, plot.height())

    def _set_off(self, v):
        self.off = max(0.0, min(self._max_off(), float(v)))
        self.update()

    def scroll_by(self, dx):
        base = self.anim.endValue() if self.anim.state() == QVariantAnimation.Running else self.off
        self.anim.stop()
        self.anim.setStartValue(self.off)
        self.anim.setEndValue(max(0.0, min(self._max_off(), base + dx)))
        self.anim.start()

    def resizeEvent(self, e):
        at_end = self.off >= self._max_off() - 1 or e.oldSize().width() <= 0
        super().resizeEvent(e)
        self.off = self._max_off() if at_end else min(self.off, self._max_off())

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        if not self.months:
            p.setPen(ink(0.5)); p.drawText(self.rect(), Qt.AlignCenter, '还没有记录'); return
        plot = self._plot()
        peak = max(sum(c.values()) for _, c in self.months)
        step = nice_step(peak)
        top = max(step, math.ceil(peak / step) * step)
        small = QFont(FONT); small.setPixelSize(11)
        label = QFont(FONT); label.setPixelSize(12)
        # 图例
        p.setFont(label)
        fm = QFontMetrics(label)
        x = plot.x()
        for gt in self.order:
            p.setPen(Qt.NoPen); p.setBrush(pool_color(gt))
            p.drawRoundedRect(QRectF(x, 8, 10, 10), 3, 3)
            p.setPen(ink(0.7)); p.drawText(QPointF(x + 15, 18), SHORT[gt])
            x += 15 + fm.horizontalAdvance(SHORT[gt]) + 20
        # 横向网格 + 纵轴数字（淡），纵轴不跟着滑
        p.setFont(small)
        for v in range(0, top + 1, step):
            y = plot.bottom() - plot.height() * v / top
            p.setPen(ink(0.25 if v == 0 else 0.08))
            p.drawLine(QPointF(plot.x(), y), QPointF(plot.right(), y))
            p.setPen(ink(0.45))
            p.drawText(QRectF(0, y - 8, self.LEFT - 8, 16), Qt.AlignRight | Qt.AlignVCenter, str(v))
        p.save()
        p.setClipRect(QRectF(plot.x(), 0, plot.width(), self.height()))
        for i, (ym, c) in enumerate(self.months):
            band = self._band(i)
            if band.right() < plot.x() or band.x() > plot.right():
                continue
            if i == self.hover:
                p.fillRect(band, ink(0.05))
            bw = min(band.width() * 0.6, 36)
            x0 = band.center().x() - bw / 2
            segs = [(gt, c[gt]) for gt in self.order if c[gt]]
            y = plot.bottom()
            for k, (gt, n) in enumerate(segs):
                h = plot.height() * n / top
                seg = QRectF(x0, y - h, bw, h - (2 if k else 0))    # 段与段之间留 2px 缝
                path = QPainterPath()
                if k == len(segs) - 1:                               # 最上面一段顶部圆角
                    r = min(4, seg.height() / 2)
                    path.addRoundedRect(seg, r, r)
                    square = QPainterPath(); square.addRect(seg.adjusted(0, r, 0, 0))
                    path = path.united(square)
                else:
                    path.addRect(seg)
                color = pool_color(gt)
                p.fillPath(path, color.darker(112) if i == self.hover else color)
                y -= h
            total = sum(c.values())
            if total:
                p.setFont(label); p.setPen(ink(0.75))
                p.drawText(QRectF(band.x() - 10, y - 20, band.width() + 20, 18), Qt.AlignHCenter | Qt.AlignBottom, str(total))
            yy, m = ym.split('-')
            p.setFont(label); p.setPen(ink(0.6))
            p.drawText(QRectF(band.x() - 10, plot.bottom() + 4, band.width() + 20, 16), Qt.AlignCenter, f'{int(m)}月')
            if i == 0 or m == '01' or band.x() <= plot.x() < band.right():    # 年份：第一个月、一月，以及滑到最左边那个月
                p.setFont(small); p.setPen(ink(0.45))
                p.drawText(QRectF(band.x() - 10, plot.bottom() + 20, band.width() + 20, 14), Qt.AlignCenter, yy)
        p.restore()
        # 两边还有月份时画个箭头提示，点了能滑过去
        af = QFont(FONT); af.setPixelSize(20); af.setBold(True); p.setFont(af); p.setPen(ink(0.4))
        if self.off > 0.5:
            p.drawText(QRectF(plot.x(), plot.y(), self.ARROW, plot.height()), Qt.AlignCenter, '‹')
        if self.off < self._max_off() - 0.5:
            p.drawText(QRectF(plot.right() - self.ARROW, plot.y(), self.ARROW, plot.height()), Qt.AlignCenter, '›')

    # ---------- 交互 ----------
    def _hit(self, pos):
        plot = self._plot()
        if not self.months or not plot.adjusted(0, 0, 0, self.BOTTOM).contains(pos):
            return None
        i = int((pos.x() - plot.x() + self.off) // self._band_w())
        return i if 0 <= i < len(self.months) else None

    def _arrow(self, pos):
        plot = self._plot()
        if not plot.contains(pos):
            return 0
        if self.off > 0.5 and pos.x() < plot.x() + self.ARROW:
            return -1
        if self.off < self._max_off() - 0.5 and pos.x() > plot.right() - self.ARROW:
            return 1
        return 0

    def wheelEvent(self, e):
        d = e.angleDelta()
        dx = d.x() or (d.y() if e.modifiers() & Qt.ShiftModifier else 0)
        if not dx or self._max_off() <= 0:
            e.ignore()                    # 竖着滚交给外面的页面
            return
        self.scroll_by(-dx)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position().x(), self.off, False)

    def mouseReleaseEvent(self, e):
        drag, self._drag = self._drag, None
        if drag is not None and not drag[2]:
            side = self._arrow(e.position())
            if side:
                self.scroll_by(side * self._plot().width() * 0.8)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            x0, off0, moved = self._drag
            dx = e.position().x() - x0
            if abs(dx) > 4 and self._max_off() > 0:
                moved = True
            self._drag = (x0, off0, moved)
            if moved:
                self.anim.stop()
                self._set_off(off0 - dx)
                QToolTip.hideText()
                return
        if self._max_off() > 0:
            self.setCursor(Qt.PointingHandCursor if self._arrow(e.position()) else Qt.OpenHandCursor)
        i = self._hit(e.position())
        if i != self.hover:
            self.hover = i
            self.update()
        if i is None:
            QToolTip.hideText(); return
        ym, c = self.months[i]
        y, m = ym.split('-')
        lines = [f'{y} 年 {int(m)} 月　共 {sum(c.values())} 抽'] + [f'{SHORT[gt]}：{c[gt]}' for gt in self.order if c[gt]]
        QToolTip.showText(e.globalPosition().toPoint(), '\n'.join(lines), self)

    def leaveEvent(self, e):
        self.hover = None
        self.update()
