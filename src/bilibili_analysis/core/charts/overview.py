"""总览图表：分区样本分布 / 快照窗口累计增量曲线（B 级）。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from bilibili_analysis.core.charts.theme import (
    MUTED,
    PINK,
    PINK_SOFT,
    apply_theme,
    counts_bar,
)


def partition_distribution(videos: pd.DataFrame) -> go.Figure:
    """分区样本分布（当前筛选内视频计数）。"""
    return counts_bar(videos["tname"], title="分区样本分布")


def view_cum_fig(curve: pd.DataFrame) -> go.Figure:
    """窗口累计增量曲线：横轴 = 观测轮次（B 级口径，head 层专属）。

    口径（03 §11 + 新增约定）：仅 head 层（榜单上榜视频）；control 不做增量展示；
    T0 为首次观测时刻（非发布时刻）；首轮之前历史不可知；仅描述、不建模、不预测。
    """
    fig = go.Figure()
    for bvid, g in curve.groupby("bvid"):
        fig.add_trace(go.Scatter(
            x=g["round"], y=g["view_cum"], mode="lines", name=str(bvid),
            line=dict(color=MUTED, width=1), opacity=0.2, showlegend=False,
            hovertemplate=f"{bvid}<br>轮次 %{{x}}：%{{y:.0f}}<extra></extra>"))
    mean = curve.groupby("round")["view_cum"].mean()
    fig.add_trace(go.Scatter(
        x=mean.index, y=mean.values, mode="lines+markers", name="head 层均值",
        line=dict(color=PINK, width=3), marker=dict(size=8, color=PINK_SOFT,
                                                    line=dict(color=PINK, width=2)),
        hovertemplate="轮次 %{x}：均值 %{y:.0f}<extra></extra>"))
    fig.update_xaxes(title="观测轮次（round）", dtick=1)
    fig.update_yaxes(title="窗口累计播放增量 view(t)−view(T0)")
    fig.add_annotation(text="T0 为首次观测时刻（非发布时刻）｜首轮之前历史不可知",
                       xref="paper", yref="paper", x=0.01, y=-0.22,
                       showarrow=False, font=dict(color=MUTED, size=11))
    return apply_theme(fig, title="窗口累计增量曲线（head 层 · 榜单上榜视频，仅描述）")


def delta_bar(delta_stats: pd.DataFrame, metric: str = "view") -> go.Figure:
    """Δ 分布柱状图：各轮次全样本 view_delta 均值（观测轮次口径）。"""
    col = f"{metric}_delta"
    if delta_stats is None or col not in getattr(delta_stats, "columns", []):
        return blank_like("Δ 数据不足")
    fig = go.Figure(go.Bar(x=list(delta_stats.columns), y=delta_stats.loc["mean"].values,
                           marker_color=PINK_SOFT,
                           hovertemplate="%{x}：%{y:.1f}<extra></extra>"))
    fig.update_xaxes(title="指标")
    fig.update_yaxes(title="相邻时点 Δ 均值")
    return apply_theme(fig, title="各指标相邻时点增量均值（Δ 汇总）")


def blank_like(message: str) -> go.Figure:
    """占位（复用 theme.blank_fig，保持导出整洁）。"""
    from bilibili_analysis.core.charts.theme import blank_fig
    return blank_fig(message)


__all__ = ["partition_distribution", "view_cum_fig", "delta_bar", "blank_like"]
