# 崩铁抽卡统计：读游戏缓存里的跃迁链接 → 拉取记录存到本地 → 统计保底、歪没歪；头像墙和海报模式展示五星
import os, sys, threading, traceback
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QFontDatabase
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QVBoxLayout, QWidget, QStackedWidget, QTableWidgetItem, QHeaderView,
                               QAbstractItemView)
if __name__ == '__main__' and QApplication.instance() is None:
    # 启动提速：第一次量文字时 Qt 要把系统字体全扫一遍（几百个字体约 0.5 秒）。先建好 QApplication，
    # 让后台线程去扫，和下面导入界面库（约 0.4 秒）同时进行。（在后台连字体文件也加载的话会和界面线程抢锁，反而更慢）
    _app = QApplication(sys.argv)
    threading.Thread(target=QFontDatabase.families, daemon=True).start()
from qfluentwidgets import (SimpleCardWidget, CaptionLabel, BodyLabel, StrongBodyLabel, TitleLabel, SubtitleLabel,
                            PrimaryPushButton, PushButton, ComboBox, SegmentedWidget, TableWidget, ProgressBar,
                            IndeterminateProgressBar, SmoothScrollArea, InfoBar, InfoBarPosition, MessageBoxBase,
                            PlainTextEdit, FluentIcon as FIF, isDarkTheme, qconfig, RoundMenu, Action, FlowLayout,
                            PillPushButton, LineEdit, CheckBox)
import gacha_api, store, stats
from gacha_api import POOLS
from images import images
from posters import AvatarWall, PosterFlow, FiveTile, SHORT
from charts import MonthlyChart
from fluent_ui import make_app, Window, show_window, single_instance

ALWAYS_SHOWN = ('11', '12', '1')          # 联动池、新手池有记录才显示
GOLD, PURPLE = QColor('#d9952a'), QColor('#8e5fd6')
VERSION = '2026.10.21'                    # 日历版本号：发布当天的日期，同一天再发就加 .1、.2
JADE_PER_PULL = 160
SIDE_MARGIN = 16                          # 窗口左右留白；海报模式的卡片不受这个限制，铺到窗口边


class StatCard(SimpleCardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12); v.setSpacing(2)
        self.title = CaptionLabel(title)
        self.title.setTextColor(QColor(0, 0, 0, 150), QColor(255, 255, 255, 160))
        self.value = TitleLabel('—')
        self.sub = CaptionLabel('')
        self.sub.setTextColor(QColor(0, 0, 0, 150), QColor(255, 255, 255, 160))
        self.bar = ProgressBar(useAni=False)
        self.bar.hide()
        for w in (self.title, self.value, self.sub, self.bar):
            v.addWidget(w)
        v.addStretch(1)

    def set(self, value, sub='', bar=None):
        self.value.setText(str(value))
        self.sub.setText(sub)
        if bar is None:
            self.bar.hide()
        else:
            self.bar.show(); self.bar.setRange(0, bar[1]); self.bar.setValue(min(bar[0], bar[1]))


def pity_text(s):
    """距上个五星已抽多少 + 下一个五星的保底状态，总览和卡池页都用。"""
    value = f'{"≥" if s.pity_uncertain else ""}{s.pity} / {s.hard_pity}'
    if not s.limited:
        nxt = ''
    elif s.guaranteed is True:
        nxt = '上个五星歪了，下个必是限定（大保底）'
    elif s.guaranteed is False:
        nxt = '下个五星是小保底，' + ('75%' if s.gacha_type in ('12', '22') else '50%') + ' 不歪'
    else:
        nxt = '还没出过五星，保底状态未知'
    return value, nxt


def off_text(s):
    n = s.not_off + s.off
    return f'不歪 {s.not_off} · 歪 {s.off}', (f'小保底不歪率 {s.not_off / n:.0%}' if n else '还没有小保底的记录')


def card_row(*cards):
    h = QHBoxLayout(); h.setSpacing(10)
    for c in cards:
        h.addWidget(c, 1)
    return h


def section(title, extra=None):
    """一张卡片 + 标题行，返回 (卡片, 放内容的竖向布局, 标题右侧的说明文字)。"""
    card = SimpleCardWidget()
    v = QVBoxLayout(card); v.setContentsMargins(16, 12, 16, 12); v.setSpacing(8)
    head = QHBoxLayout(); head.setSpacing(12)
    head.addWidget(StrongBodyLabel(title))
    note = CaptionLabel('')
    note.setTextColor(QColor(0, 0, 0, 150), QColor(255, 255, 255, 160))
    head.addWidget(note); head.addStretch(1)
    if extra is not None:
        head.addWidget(extra)
    v.addLayout(head)
    return card, v, note


def scroll_of(widget):
    s = SmoothScrollArea(); s.setWidgetResizable(True); s.setWidget(widget)
    s.setStyleSheet('QScrollArea{background:transparent;border:none}')
    # 只透明这一层：不带选择器的 background:transparent 会传给里面的提示框，提示框就变成一个黑框
    widget.setObjectName('scrollBody')
    widget.setStyleSheet('#scrollBody{background:transparent}')
    return s


class PoolPage(QWidget):
    def __init__(self, gacha_type, parent=None):
        super().__init__(parent)
        self.gt = gacha_type
        self.records = []
        v = QVBoxLayout(self); v.setContentsMargins(SIDE_MARGIN, 0, SIDE_MARGIN, 0); v.setSpacing(10)
        self.c_pity, self.c_total, self.c_five = StatCard('已抽'), StatCard('总抽数'), StatCard('五星')
        cards = [self.c_pity, self.c_total, self.c_five]
        if gacha_type in stats.LIMITED:
            self.c_up = StatCard('UP 情况')
            cards.append(self.c_up)
        v.addLayout(card_row(*cards))

        body = QHBoxLayout(); body.setSpacing(10)
        left, lv, self.wall_note = section('五星记录')
        self.wall = AvatarWall()
        lv.addWidget(scroll_of(self.wall), 1)

        self.filter = SegmentedWidget()
        for key, text in (('all', '全部'), ('5', '五星'), ('4', '四星')):
            self.filter.addItem(key, text, onClick=lambda *_, k=key: self.fill_table(k))
        self.filter.setCurrentItem('all')
        right, rv, self.table_note = section('抽卡记录', self.filter)
        self.table = TableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['时间', '名称', '类型', '第几抽'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setBorderVisible(True); self.table.setBorderRadius(8); self.table.setWordWrap(False)
        # 列宽按表头和最长内容一次算好定死；按内容自动调宽要逐行量，上千行时很慢
        hh = self.table.horizontalHeader()
        fm = self.table.fontMetrics()
        for col, sample in ((0, '2026-10-19 22:11:25'), (2, '类型类型'), (3, '第几抽抽')):    # 单元格字号和内边距比默认字体大，多留一点
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, fm.horizontalAdvance(sample) + 48)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        rv.addWidget(self.table, 1)
        body.addWidget(left, 5); body.addWidget(right, 4)
        v.addLayout(body, 1)
        self._stale = True                # 表格等这一页真正显示时才填，启动时不用把几千行都建出来
        qconfig.themeChanged.connect(self._refill)

    def set_data(self, s, records):
        self.records = [r for r in records if r['gacha_type'] == self.gt]
        self.c_pity.set(*pity_text(s), bar=(s.pity, s.hard_pity))
        sub = f'折合星琼 {s.total * JADE_PER_PULL:,}'
        self.c_total.set(f'{s.total:,}', sub)
        avg = s.avg
        self.c_five.set(len(s.fives), f'平均 {avg:.1f} 抽出金' if avg else '出金平均：暂无可算的')
        if s.limited:
            self.c_up.set(*off_text(s))
        self.wall.set_data(s.fives, s.hard_pity, s.pity)
        self.wall_note.setText('鼠标移上去看详情')
        self.table_note.setText(f'数据起始于 {s.first_time[:10]}' if s.first_time else '还没有记录')
        self._stale = True
        self._refill()

    def _refill(self):
        if self.isVisible():
            self._stale = False
            self.fill_table(self.filter.currentRouteKey() or 'all')
        else:
            self._stale = True

    def showEvent(self, e):
        super().showEvent(e)
        if self._stale:
            self._refill()

    def fill_table(self, rank):
        rows, n = [], 0
        for r in self.records:                   # 记录是从旧到新排好的，顺着数“距上个五星第几抽”
            n += 1
            if rank == 'all' or r['rank_type'] == rank:
                rows.append((r, n))
            if r['rank_type'] == '5':
                n = 0
        rows.reverse()
        self.table.setRowCount(len(rows))
        for i, (r, n) in enumerate(rows):
            color = GOLD if r['rank_type'] == '5' else PURPLE if r['rank_type'] == '4' else None
            if color is not None and isDarkTheme():
                color = color.lighter(135)
            stars = {'5': '★5 ', '4': '★4 '}.get(r['rank_type'], '')
            for j, text in enumerate((r['time'], stars + r['name'], r['item_type'], str(n))):
                it = QTableWidgetItem(text)
                if color is not None:
                    it.setForeground(color)
                if j == 3:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, j, it)


class NewbieCard(SimpleCardWidget):
    """总览里的新手跃迁：只放出的那个五星（头像 + 第几抽出的），不再单独占一段头像墙。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 36, 12); h.setSpacing(12)      # 右边多留点，头像不贴边，看着平衡
        self.tile = FiveTile()
        h.addWidget(SubtitleLabel(POOLS['2'][0]), 0, Qt.AlignTop); h.addStretch(1)
        h.addWidget(self.tile, 0, Qt.AlignVCenter)

    def set(self, s):
        self.tile.set_data(s.fives[-1] if s.fives else None, s.hard_pity, s.pity)


class Overview(QWidget):
    """总览：汇总数字 + 各池已抽 + 每月抽数 + 每个池子一段头像墙（小黑盒那样）。整页一起滚动。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self); outer.setContentsMargins(SIDE_MARGIN, 0, SIDE_MARGIN, 0)
        inner = QWidget()
        v = QVBoxLayout(inner); v.setContentsMargins(0, 0, 6, 0); v.setSpacing(10)
        self.c_total, self.c_jade, self.c_five, self.c_off = StatCard('总抽数'), StatCard('折合星琼'), StatCard('五星总数'), StatCard('UP 情况')
        v.addLayout(card_row(self.c_total, self.c_jade, self.c_five, self.c_off))
        self.pity_cards = {gt: StatCard(f'{POOLS[gt][0]} · 已抽') for gt in POOLS if gt != '2'}
        self.newbie = NewbieCard()
        v.addLayout(card_row(*self.pity_cards.values(), self.newbie))
        self.month_card, mv, self.month_note = section('每月抽数')
        self.monthly = MonthlyChart()
        mv.addWidget(self.monthly)
        v.addWidget(self.month_card)
        self.sections = {}
        for gt in POOLS:
            if gt == '2':                 # 新手跃迁只有一个五星，放在上面的卡片里
                continue
            card, cv, note = section(POOLS[gt][0])
            wall = AvatarWall()
            cv.addWidget(wall)
            v.addWidget(card)
            self.sections[gt] = (card, wall, note)
        self.empty = SubtitleLabel('还没有记录。先在游戏里打开一次「跃迁 → 查看详情」，再点右上角「更新记录」')
        self.empty.setAlignment(Qt.AlignCenter); self.empty.setWordWrap(True)
        v.addWidget(self.empty)
        v.addStretch(1)
        outer.addWidget(scroll_of(inner))

    def set_data(self, st, records):
        total = sum(s.total for s in st.values())
        fives = [f for s in st.values() for f in s.fives]
        known = [f.pulls for f in fives if not f.uncertain and f.pulls]
        self.c_total.set(f'{total:,}')
        self.c_jade.set(f'{total * JADE_PER_PULL:,}', '每抽按 160 星琼算')
        self.c_five.set(len(fives), f'平均 {sum(known) / len(known):.1f} 抽出金（全部卡池）' if known else '')
        merged = stats.PoolStats('11', '', 90, True)          # 角色和光锥的限定池合起来算
        merged.fives = [f for gt in stats.LIMITED for f in st[gt].fives]
        self.c_off.set(*off_text(merged))
        for gt, card in self.pity_cards.items():
            s = st[gt]
            card.setVisible(gt in ALWAYS_SHOWN or s.total > 0)
            card.set(*pity_text(s), bar=(s.pity, s.hard_pity))
        self.newbie.setVisible(st['2'].total > 0)
        self.newbie.set(st['2'])
        self.month_card.setVisible(bool(records))
        self.monthly.set_data(records)
        self.month_note.setText(f'数据起始于 {min(r["time"] for r in records)[:10]}' if records else '')
        for gt, (card, wall, note) in self.sections.items():
            s = st[gt]
            card.setVisible(s.total > 0)
            parts = [f'{s.total:,} 抽', f'{len(s.fives)} 个五星']
            if s.avg:
                parts.append(f'平均 {s.avg:.1f} 抽')
            if s.limited and s.not_off + s.off:
                parts.append(f'不歪率 {s.not_off / (s.not_off + s.off):.0%}')
            note.setText('　·　'.join(parts))
            wall.set_data(s.fives, s.hard_pity, s.pity)
        self.empty.setVisible(total == 0)


class PosterPage(QWidget):
    """海报模式：每个五星一张大卡片，左右滑动。上面勾选要看哪些卡池，可以任意组合。卡片一直铺到窗口左右边缘。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(6)
        top = QHBoxLayout(); top.setContentsMargins(SIDE_MARGIN, 0, SIDE_MARGIN, 0); top.setSpacing(18)
        self.checks = {}
        for gt in POOLS:
            c = CheckBox(SHORT[gt]); c.setChecked(True)
            c.stateChanged.connect(lambda *_: self.apply())
            top.addWidget(c)
            self.checks[gt] = c
        self.counter = CaptionLabel('')
        self.counter.setTextColor(QColor(0, 0, 0, 150), QColor(255, 255, 255, 160))
        top.addStretch(1); top.addWidget(self.counter)
        v.addLayout(top)
        self.flow = PosterFlow()
        self.flow.focusChanged.connect(lambda i, n: self.counter.setText(f'第 {i} / {n} 个五星　·　滚轮、拖动或 ← → 切换，点卡片跳过去'))
        v.addWidget(self.flow, 1)
        self.st = {}

    def set_data(self, st):
        self.st = st
        for gt, c in self.checks.items():
            c.setVisible(st[gt].total > 0)
        self.apply()

    def apply(self):
        """新手跃迁的五星一定是最早的，放最前；然后是没有时间的（截图导入的），其余按时间排。"""
        chosen = [gt for gt, c in self.checks.items() if c.isChecked() and gt in self.st]
        newbie = self.st['2'].fives if '2' in chosen else []
        rest = [f for gt in chosen if gt != '2' for f in self.st[gt].fives]
        fives = newbie + [f for f in rest if not f.time] + sorted((f for f in rest if f.time), key=lambda f: f.time)
        self.flow.set_data(fives)
        if not fives:
            self.counter.setText('没有勾选卡池' if not chosen else '')


class PoolDialog(MessageBoxBase):
    """歪池设置：选出你在游戏「星缘相邀」里选的角色。"""
    KNOWN = ['云璃', '希儿', '银狼', '刃', '符玄', '银枝']      # 目前「星缘相邀」能选的旧限定（用户 2026-10-20 给的名单）

    def __init__(self, parent, chosen):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel('歪池设置'))
        tip = BodyLabel('3.2 版本起，角色跃迁里会歪出来的 7 个角色由你在游戏「星缘相邀」里自己选。'
                        f'常驻的 {"、".join(stats.STANDARD_CHARS)} 总是算歪；'
                        '下面点亮你额外选进歪池的角色（每个账号分开记）。\n'
                        '同一个卡池里出过不同五星时，工具会自动认出 UP，不看这个名单；单个判断不对的，可以在五星上右键手动改。')
        tip.setWordWrap(True)
        self.viewLayout.addWidget(tip)
        names = list(dict.fromkeys(self.KNOWN + sorted(chosen)))
        names = [n for n in names if n not in stats.STANDARD_CHARS]
        box = QWidget()
        self.flow = FlowLayout(box, needAni=False)
        self.flow.setHorizontalSpacing(8); self.flow.setVerticalSpacing(8)
        self.pills = {}
        for n in names:
            self._add(n, n in chosen)
        self.viewLayout.addWidget(box)
        row = QHBoxLayout()
        self.edit = LineEdit(); self.edit.setPlaceholderText('不在上面的角色，输入名字后点添加')
        add = PushButton('添加')
        add.clicked.connect(self._add_typed)
        row.addWidget(self.edit, 1); row.addWidget(add)
        self.viewLayout.addLayout(row)
        self.yesButton.setText('保存'); self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(620)

    def _add(self, name, checked):
        b = PillPushButton(name); b.setCheckable(True); b.setChecked(checked)
        self.flow.addWidget(b)
        self.pills[name] = b

    def _add_typed(self):
        n = self.edit.text().strip()
        if n and n not in self.pills and n not in stats.STANDARD_CHARS:
            self._add(n, True)
        elif n in self.pills:
            self.pills[n].setChecked(True)
        self.edit.clear()

    def chosen(self):
        return [n for n, b in self.pills.items() if b.isChecked()]


class LinkDialog(MessageBoxBase):
    def __init__(self, parent):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel('粘贴跃迁记录链接'))
        tip = BodyLabel('平时直接点「更新记录」就行，工具会自己从游戏缓存里找链接。找不到时才用这里：'
                        '把含有链接的内容整段粘贴进来（只有链接也行），工具会自己挑出链接；链接只在这次更新时使用，不会保存。')
        tip.setWordWrap(True)
        self.viewLayout.addWidget(tip)
        self.edit = PlainTextEdit()
        self.edit.setPlaceholderText('https://public-operation-hkrpg.mihoyo.com/…getGachaLog?…authkey=…')
        self.edit.setFixedHeight(110)
        clip = QGuiApplication.clipboard().text().strip()
        if 'GachaLog' in clip:
            self.edit.setPlainText(clip)
        self.viewLayout.addWidget(self.edit)
        self.yesButton.setText('开始更新'); self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(520)

    def url(self):
        return self.edit.toPlainText().strip()


class App(Window):
    sig_progress = Signal(str)
    sig_done = Signal(str, dict)
    sig_error = Signal(str)

    def __init__(self):
        super().__init__(f'崩铁抽卡统计  {VERSION}')
        self.setWindowIcon(QIcon(os.path.join(store.RES, 'icon.ico')))
        self.settings = store.load_settings()
        self.resize(*self.settings.get('size', (1180, 800)))
        self.setMinimumSize(980, 660)
        m = self.body.contentsMargins()            # 左右留白交给各行自己加，海报模式才能铺到窗口边
        self.body.setContentsMargins(0, m.top(), 0, m.bottom())

        top = QHBoxLayout(); top.setSpacing(8); top.setContentsMargins(SIDE_MARGIN, 0, SIDE_MARGIN, 0)
        self.uid_box = ComboBox(); self.uid_box.setMinimumWidth(170)
        self.uid_box.currentIndexChanged.connect(lambda _: self.refresh())
        self.status = CaptionLabel('')
        self.status.setTextColor(QColor(0, 0, 0, 150), QColor(255, 255, 255, 160))
        self.btn_folder = PushButton(FIF.PHOTO, '图片文件夹')
        self.btn_folder.setToolTip('自定义海报和头像：把图片按角色名命名放进「自定义」文件夹')
        self.btn_folder.clicked.connect(lambda: os.startfile(os.path.join(store.HERE, '图片', '自定义')))
        self.btn_pool = PushButton(FIF.SETTING, '歪池设置')
        self.btn_pool.clicked.connect(self.edit_pool)
        self.btn_paste = PushButton(FIF.LINK, '粘贴链接')
        self.btn_update = PrimaryPushButton(FIF.SYNC, '更新记录')
        self.btn_update.setToolTip('从游戏缓存里自动找链接并拉取新记录。用之前先在游戏里打开一次「跃迁 → 查看详情」')
        self.btn_paste.clicked.connect(self.paste_link)
        self.btn_update.clicked.connect(lambda: self.start_update(None))
        top.addWidget(self.uid_box); top.addWidget(self.status, 1)
        top.addWidget(self.btn_pool); top.addWidget(self.btn_folder); top.addWidget(self.btn_paste); top.addWidget(self.btn_update)
        self.body.addLayout(top)
        self.busy = IndeterminateProgressBar(); self.busy.hide()
        row = QHBoxLayout(); row.setContentsMargins(SIDE_MARGIN, 0, SIDE_MARGIN, 0); row.addWidget(self.busy)
        self.body.addLayout(row)

        self.tabs = SegmentedWidget()
        self.stack = QStackedWidget()
        self.overview = Overview()
        self.pages = {gt: PoolPage(gt) for gt in POOLS if gt != '2'}     # 新手跃迁不单独开页，总览卡片里看
        self.posters = PosterPage()
        self._add_tab('overview', '总览', self.overview)
        for gt, page in self.pages.items():
            self._add_tab(gt, SHORT[gt], page)
        self._add_tab('posters', '海报模式', self.posters)
        self.tabs.setCurrentItem('overview')
        row = QHBoxLayout(); row.setContentsMargins(SIDE_MARGIN, 0, SIDE_MARGIN, 0)
        row.addWidget(self.tabs); row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(self.stack, 1)

        walls = [w for _, w, _ in self.overview.sections.values()] + [p.wall for p in self.pages.values()]
        for w in walls + [self.posters.flow]:
            w.markRequested.connect(self.mark_menu)

        self.sig_progress.connect(self.status.setText)
        self.sig_done.connect(self.on_done)
        self.sig_error.connect(self.on_error)
        self.load_uids(self.settings.get('uid'))

    def _add_tab(self, key, text, page):
        self.stack.addWidget(page)
        self.tabs.addItem(key, text, onClick=lambda *_, p=page: self.stack.setCurrentWidget(p))

    def load_uids(self, select=None):
        ids = store.uids()
        self.uid_box.blockSignals(True)
        self.uid_box.clear()
        for u in ids:
            self.uid_box.addItem(f'UID {u}', userData=u)
        if select in ids:
            self.uid_box.setCurrentIndex(ids.index(select))
        self.uid_box.setVisible(bool(ids))
        self.uid_box.blockSignals(False)
        self.refresh()

    def uid(self):
        return self.uid_box.currentData() if self.uid_box.count() else None

    def refresh(self):
        uid = self.uid()
        doc = store.load(uid) if uid else {'records': [], 'updated_at': ''}
        st = stats.all_stats(doc)
        self.overview.set_data(st, doc['records'])
        for gt, page in self.pages.items():
            page.set_data(st[gt], doc['records'])
            self.tabs.items[gt].setVisible(gt in ALWAYS_SHOWN or st[gt].total > 0)
        self.posters.set_data(st)
        images().forget()           # 「自定义」里可能放了新图
        # 提前把要用的图都排进下载队列
        items = {(f.item_id, f.name) for s in st.values() for f in s.fives}
        images().request([(k, i, n) for i, n in items for k in ('avatar', 'poster')])
        self.status.setText(f'上次更新：{doc["updated_at"]}' if doc.get('updated_at') else '')

    # ---------- 歪没歪 ----------
    def mark_menu(self, f, pos):
        if f.gacha_type not in stats.LIMITED or not self.uid():
            return
        menu = RoundMenu(parent=self)
        for text, value in (('标为歪', '歪'), ('标为不歪', '不歪'), ('恢复自动判断', None)):
            a = Action(text + ('　✓' if (value is None and not f.manual) else ''), self)
            a.triggered.connect(lambda *_, v=value: self.set_mark(f.key, v))
            menu.addAction(a)
        menu.exec(pos)

    def set_mark(self, key, value):
        doc = store.load(self.uid())
        ov = doc.setdefault('overrides', {})
        if value is None:
            ov.pop(key, None)
        else:
            ov[key] = value
        store.save(doc)
        self.refresh()

    def edit_pool(self):
        """歪池按账号存：改的是当前 UID 的 data/<uid>.json。"""
        if not self.uid():
            InfoBar.info('还没有账号', '先点「更新记录」拉取一次抽卡记录，再设置歪池', duration=4000, position=InfoBarPosition.TOP, parent=self)
            return
        doc = store.load(self.uid())
        d = PoolDialog(self, set(stats.chosen_names(doc)))
        if d.exec():
            doc['星缘相邀'] = d.chosen()
            store.save(doc)
            self.refresh()

    # ---------- 更新 ----------
    def paste_link(self):
        d = LinkDialog(self)
        if d.exec():
            self.start_update(d.url())

    def start_update(self, url):
        self.btn_update.setEnabled(False); self.btn_paste.setEnabled(False)
        self.busy.show(); self.busy.start()
        self.status.setText('正在找链接…' if url is None else '正在连接…')
        threading.Thread(target=self._work, args=(url,), daemon=True).start()

    def _work(self, url):
        try:
            if url is None:
                url = gacha_api.find_url_in_cache()
                if url is None:
                    raise gacha_api.GachaError('没在游戏缓存里找到链接。请先打开游戏，进入「跃迁 → 查看详情」，再点更新；'
                                               '或者用「粘贴链接」')
            uid, tz, recs = gacha_api.fetch(url, store.known_ids, self.sig_progress.emit)
            added = store.merge(uid, tz, recs)
            self.sig_done.emit(uid, added)
        except gacha_api.GachaError as e:
            self.sig_error.emit(str(e))
        except Exception as e:
            traceback.print_exc()
            self.sig_error.emit(f'出错了：{e}')

    def _idle(self):
        self.btn_update.setEnabled(True); self.btn_paste.setEnabled(True)
        self.busy.stop(); self.busy.hide()

    def on_done(self, uid, added):
        self._idle()
        self.load_uids(uid)
        if added:
            text = '，'.join(f'{SHORT[gt]} {n} 条' for gt, n in added.items())
            InfoBar.success('更新完成', f'新增 {text}', duration=5000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.info('更新完成', '没有新记录', duration=3000, position=InfoBarPosition.TOP, parent=self)

    def on_error(self, msg):
        self._idle()
        self.refresh()
        InfoBar.error('更新失败', msg, duration=-1, position=InfoBarPosition.TOP, parent=self)

    def closeEvent(self, e):
        self.settings.update(uid=self.uid(), size=[self.width(), self.height()])
        store.save_settings(self.settings)
        super().closeEvent(e)


class ErrorLog:
    """exe 没有控制台：报错写到旁边的 log.txt。真有内容要写时才建文件，正常运行不留空的 log.txt"""
    file = None

    def write(self, s):
        if self.file is None:
            self.file = open(os.path.join(store.HERE, 'log.txt'), 'w', encoding='utf-8', buffering=1)
        return self.file.write(s)

    def flush(self):
        if self.file:
            self.file.flush()

    def isatty(self):
        return False


def main():
    if getattr(sys, 'frozen', False) and sys.stderr is None:
        sys.stdout = sys.stderr = ErrorLog()
    app = make_app()
    win = None
    if not single_instance('hsr-gacha-stats', lambda: win):
        return
    images().preload()          # 搭窗口的同时在后台把图片解码好
    win = App()
    show_window(win)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
