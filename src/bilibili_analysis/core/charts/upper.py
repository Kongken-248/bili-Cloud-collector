"""UP主分析图表：粉丝量级 / 投稿构成 / 破圈四象限散点 / 聚类 K 选择与类中心。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from bilibili_analysis.core.charts.theme import (
    BLUE,
    CONTROL_COLOR,
    HEAD_COLOR,
    MUTED,
    PINK,
    PINK_SOFT,
    SOFT,
    TEAL,
    apply_theme,
    color_for_partition,
    counts_bar,
)

# 四象限固定色（跨页一致）：低饱和点缀，呼应 F2 色板
QUADRANT_COLORS = {
    "头部高破圈": PINK,
    "头部低破圈": BLUE,
    "小身高破圈": TEAL,
    "小身低破圈": MUTED,
}


def fans_hist_fig(uppers: pd.DataFrame) -> go.Figure:
    """粉丝量级分布（log 轴直方图）；输入 uppers 表。"""
    fans = uppers["fans"].dropna()
    fans = fans[fans > 0]
    fig = go.Figure(go.Histogram(x=np.log10(fans), marker_color=PINK_SOFT,
                                 hovertemplate="log10(粉丝) %{x:.2f}：%{y} 个<extra></extra>"))
    fig.update_xaxes(title="log10(粉丝数)")
    fig.update_yaxes(title="UP主数")
    return apply_theme(fig, title="粉丝量级分布（log 轴）")


def up_post_fig(stats: pd.DataFrame) -> go.Figure:
    """UP主投稿构成：head / control 堆叠条形；输入 upper_stats()。"""
    df = stats.dropna(subset=["name"]).copy()
    df["label"] = df["name"] + "（" + df["mid"].astype(str) + "）"
    fig = go.Figure()
    fig.add_trace(go.Bar(name="head", x=df["label"], y=df["head_count"].fillna(0),
                         marker_color=HEAD_COLOR))
    fig.add_trace(go.Bar(name="control", x=df["label"], y=df["control_count"].fillna(0),
                         marker_color=CONTROL_COLOR))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="投稿数")
    return apply_theme(fig, title="UP主投稿构成（head / control）")


def quadrant_scatter_fig(table: pd.DataFrame, x_split: float, y_split: float) -> go.Figure:
    """破圈四象限散点：X=粉丝（log）、Y=破圈度，悬停显示 UP主与代表视频。"""
    fig = go.Figure()
    for quad, g in table.groupby("quadrant"):
        fig.add_trace(go.Scatter(
            x=g["fans"], y=g["breakout"], mode="markers", name=quad,
            marker=dict(color=QUADRANT_COLORS.get(quad, BLUE), size=12, opacity=0.85),
            customdata=np.stack([g["name"], g["top_video"].fillna(""),
                                 g["median_view"].fillna(0)], axis=-1),
            hovertemplate=("%{customdata[0]}（UP主）<br>代表视频：%{customdata[1]}"
                           "<br>粉丝 %{x:.0f}｜破圈度 %{y:.3f}"
                           "<br>head 中位播放 %{customdata[2]:.0f}<extra></extra>")))
    fig.update_xaxes(type="log", title="粉丝量（log 轴）")
    fig.update_yaxes(title="破圈度（head 中位播放 / 粉丝）")
    fig.add_vline(x=x_split, line=dict(color=MUTED, width=1, dash="dash"))
    fig.add_hline(y=y_split, line=dict(color=MUTED, width=1, dash="dash"))
    fig.add_annotation(text="分界线 = 中位数", xref="paper", yref="paper",
                       x=0.02, y=0.98, showarrow=False, font=dict(color=MUTED, size=11))
    return apply_theme(fig, height=460, title="破圈四象限（分界线取中位数）")


def k_score_fig(score_df: pd.DataFrame, best_k: int) -> go.Figure:
    """K 选择依据双轴图：柱=肘部 inertia，线=轮廓系数；标注最优 K。"""
    fig = go.Figure()
    fig.add_trace(go.Bar(x=score_df["k"], y=score_df["inertia"], name="肘部 inertia",
                         marker_color=SOFT, yaxis="y"))
    fig.add_trace(go.Scatter(x=score_df["k"], y=score_df["silhouette"],
                             name="轮廓系数", mode="lines+markers",
                             marker_color=TEAL, yaxis="y2"))
    fig.update_layout(yaxis=dict(title="inertia"), yaxis2=dict(
        title="轮廓系数", overlaying="y", side="right", showgrid=False))
    fig.update_xaxes(title="聚类数 K", dtick=1)
    fig.add_annotation(text=f"最优 K = {best_k}（轮廓系数最大）", xref="paper",
                       yref="paper", x=0.98, y=0.95, showarrow=False,
                       font=dict(color=MUTED, size=12))
    return apply_theme(fig, title="KMeans 聚类 K 选择（肘部 + 轮廓系数）")


def centers_heatmap_fig(centers: pd.DataFrame) -> go.Figure:
    """类中心对比热力图（标准化后中心值）；输入 cluster centers 表。"""
    z = centers.values
    fig = go.Figure(go.Heatmap(
        z=z, x=list(centers.columns), y=[f"类{i}" for i in range(len(centers))],
        colorscale=[[0, BLUE], [0.5, PINK_SOFT], [1, PINK]], zmid=0,
        xgap=2, ygap=2, hovertemplate="%{y} · %{x}：%{z:.3f}<extra></extra>"))
    return apply_theme(fig, title="类中心对比（标准化特征，log 变换后）")


__all__ = ["counts_bar", "fans_hist_fig", "up_post_fig", "quadrant_scatter_fig",
           "k_score_fig", "centers_heatmap_fig", "color_for_partition"]
