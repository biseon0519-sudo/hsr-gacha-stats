# 各页面共用的小部件：数字卡片、带标题的分区卡片、透明滚动区、灰色说明文字
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import SimpleCardWidget, CaptionLabel, TitleLabel, StrongBodyLabel, ProgressBar, SmoothScrollArea

SIDE_MARGIN = 16                          # 窗口左右留白；海报模式的卡片不受这个限制，铺到窗口边


def muted(text=''):
    """浅一点的小字（说明、计数）。"""
    label = CaptionLabel(text)
    label.setTextColor(QColor(0, 0, 0, 150), QColor(255, 255, 255, 160))
    return label


class StatCard(SimpleCardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12); v.setSpacing(2)
        self.title = muted(title)
        self.value = TitleLabel('—')
        self.sub = muted()
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
    note = muted()
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
