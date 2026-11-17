"""图表主题与通用工具：「F2 纸白追番站」视觉唯一真源。

色值提取自已确认原型「B站视频数据分析系统-五页面精细原型.html」，
跨页一致：分区固定色板、head/control 固定色、纸白底 + 暖白卡片 + 低饱和粉点缀。
所有图表函数统一经 apply_theme() 出图；空数据用 blank_fig() 降级，不白屏。
"""

from __future__ import annotations

import plotly.graph_objects as go
import pandas as pd

# ---------------------------------------------------------------------------
# F2 原型色值（跨页唯一写法，禁止在别处硬编码）
# ---------------------------------------------------------------------------
PAPER = "#f5f2eb"       # 页面浅纸底
CARD = "#fffdf8"        # 暖白卡片
SOFT = "#f0ebe3"        # 浅灰米
SIDE = "#eee9df"        # 侧边栏底
INK = "#302d31"         # 墨色正文
MUTED = "#756f72"       # 弱化文字
LINE = "#ded8d2"        # 分隔线 / 网格
PINK = "#df7092"        # 主点缀粉
PINK_SOFT = "#f8dce5"   # 浅粉选中态
TEAL = "#6fa8a6"        # 青绿
BLUE = "#7d96b3"        # 雾蓝
GOOD = "#5c917d"        # 暖绿
YELLOW = "#d1aa62"      # 暖黄

# head / control 固定色（全部图表跨页一致）
HEAD_COLOR = PINK
CONTROL_COLOR = TEAL
GROUP_COLORS = {"head": HEAD_COLOR, "control": CONTROL_COLOR}

# 分区固定色板（图例跨页一致；未知分区落到雾蓝）
PARTITION_COLORS: dict[str, str] = {
    "游戏": PINK,
    "动画": TEAL,
    "知识": BLUE,
    "美食": YELLOW,
    "影视": GOOD,
    "科技数码": "#b07ea8",
}
COLOR_SEQUENCE = [PINK, TEAL, BLUE, YELLOW, GOOD, "#b07ea8"]


def color_for_partition(tname) -> str:
    """分区 → 固定色；缺省分区回退雾蓝。"""
    return PARTITION_COLORS.get(tname, BLUE)


def apply_theme(fig: go.Figure, height: int = 380, title: str | None = None) -> go.Figure:
    """统一主题：透明纸底 + 暖白绘图区 + 墨色文字 + 弱网格。"""
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=46, b=10),
        title=title, title_font=dict(size=15, color=INK),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=CARD,
        font=dict(color=INK, size=13,
                  family="Archivo, Consolas, 'Microsoft YaHei', sans-serif"),
        hoverlabel=dict(bgcolor=CARD, bordercolor=LINE, font_color=INK),
        legend=dict(orientation="h", yanchor="top", y=-0.14, x=0),
    )
    fig.update_xaxes(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE)
    fig.update_yaxes(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE)
    return fig


def blank_fig(message: str, height: int = 300) -> go.Figure:
    """空数据占位图（降级矩阵：不白屏、不抛红框）。"""
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper",
                       showarrow=False, font=dict(color=MUTED, size=14))
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def wordcloud_html(words: list[tuple[str, int]], max_px: int = 40, min_px: int = 13) -> str:
    """词云 HTML（免新增依赖）：按频次缩放字号 + 低饱和固定色板。

    words：[(词, 频次)]；频次越高字号越大。包裹进暖白卡片，贴合 F2 视觉。
    """
    if not words:
        return ""
    top = words[0][1] or 1
    spans = []
    for i, (word, count) in enumerate(words):
        size = int(min_px + (max_px - min_px) * count / top)
        color = COLOR_SEQUENCE[i % len(COLOR_SEQUENCE)]
        spans.append(
            f'<span style="font-size:{size}px;color:{color};margin:0 10px;">{word}</span>')
    return ('<div style="background:#fffdf8;border:1px solid #ded8d2;border-radius:12px;'
            'padding:20px 10px;text-align:center;line-height:2.1;">'
            + "".join(spans) + "</div>")


def counts_bar(counts: pd.Series, title: str, height: int = 380) -> go.Figure:
    """类别计数条形图，按类别固定色板着色（分区构成 / 分区样本分布复用）。"""
    counts = counts.dropna().sort_values(ascending=False)
    fig = go.Figure(go.Bar(
        x=counts.index, y=counts.values,
        marker_color=[color_for_partition(t) for t in counts.index],
        hovertemplate="%{x}：%{y} 条<extra></extra>"))
    return apply_theme(fig, height=height, title=title)
