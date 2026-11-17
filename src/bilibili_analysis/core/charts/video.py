"""视频分析图表：画像四图 + 配对差值分布 + 回归森林图。

输入一律为 analytics 子包的结构化输出（DataFrame/dict），本层只做展示。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from bilibili_analysis.core.charts.theme import (
    CONTROL_COLOR,
    GROUP_COLORS,
    HEAD_COLOR,
    LINE,
    MUTED,
    PINK,
    PINK_SOFT,
    apply_theme,
)


def view_dist_fig(df: pd.DataFrame) -> go.Figure:
    """各分区播放量分布（log 轴），head/control 分层；输入 view_distribution()。"""
    fig = px.box(df, x="tname", y="latest_view", color="sample_group", points="all",
                 color_discrete_map=GROUP_COLORS)
    fig.update_yaxes(type="log", title="播放量（log 轴）")
    fig.update_xaxes(title="分区")
    return apply_theme(fig, title="各分区播放量分布（head / control 分层）")


def duration_hist_fig(df: pd.DataFrame) -> go.Figure:
    """时长分布直方图，head/control 叠加；输入 duration_distribution()。"""
    fig = px.histogram(df, x="duration", color="sample_group", nbins=30,
                       barmode="overlay", opacity=0.75,
                       color_discrete_map=GROUP_COLORS)
    fig.update_xaxes(title="时长（秒）")
    fig.update_yaxes(title="视频数")
    return apply_theme(fig, title="时长分布")


def pub_heatmap_fig(df: pd.DataFrame) -> go.Figure:
    """发布时段热力（星期 × 小时投稿计数）；输入 pub_hour_heatmap()。"""
    days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    piv = df.pivot_table(index="weekday", columns="hour", values="count",
                         fill_value=0).reindex(index=range(7), columns=range(24), fill_value=0)
    fig = go.Figure(go.Heatmap(
        z=piv.values, x=list(range(24)), y=days, colorscale=[[0, PINK_SOFT], [1, PINK]],
        xgap=1, ygap=1, hovertemplate="%{y} %{x} 点：%{z} 条<extra></extra>"))
    return apply_theme(fig, title="发布时段热力（星期 × 小时）")


def title_len_fig(df: pd.DataFrame) -> go.Figure:
    """标题长度分布直方图，head/control 叠加；输入 title_length_distribution()。"""
    fig = px.histogram(df, x="title_len", color="sample_group", nbins=25,
                       barmode="overlay", opacity=0.75,
                       color_discrete_map=GROUP_COLORS)
    fig.update_xaxes(title="标题长度（字符）")
    fig.update_yaxes(title="视频数")
    return apply_theme(fig, title="标题长度分布")


def pair_diff_fig(pairs: pd.DataFrame, feature_label: str = "log 播放量") -> go.Figure:
    """配对差值分布：head − 同 UP主 control 中位数，零参考虚线；输入 pairs 表。"""
    diff = (pairs["head"] - pairs["control"]).dropna()
    fig = px.histogram(x=diff, nbins=30)
    fig.update_traces(marker_color=PINK,
                      hovertemplate="差值 %{x:.3f}：%{y} 对<extra></extra>")
    fig.add_vline(x=0, line=dict(color=MUTED, width=1.5, dash="dash"),
                  annotation_text="head = control", annotation_position="top")
    fig.update_xaxes(title=f"配对差值（{feature_label}，head − control 中位数）")
    fig.update_yaxes(title="配对数")
    return apply_theme(fig, title="配对差值分布（同主体对照）")


def forest_fig(coef: pd.DataFrame) -> go.Figure:
    """回归系数森林图（95% CI + 零参考线）；输入回归 coef_table（去掉 const）。"""
    coef = coef.drop(index="const", errors="ignore").sort_values("系数")
    fig = go.Figure(go.Scatter(
        x=coef["系数"], y=coef.index, mode="markers",
        marker=dict(color=HEAD_COLOR, size=10),
        error_x=dict(type="data",
                     array=(coef["CI上限"] - coef["系数"]).clip(lower=0),
                     arrayminus=(coef["系数"] - coef["CI下限"]).clip(lower=0),
                     color=MUTED, thickness=1.5),
        customdata=np.stack([coef["标准误"], coef["p值"]], axis=-1),
        hovertemplate=("%{y}<br>系数=%{x:.4f}<br>标准误=%{customdata[0]:.4f}"
                       "<br>p=%{customdata[1]:.4f}<extra></extra>")))
    fig.add_vline(x=0, line=dict(color=LINE, width=1.5, dash="dash"),
                  annotation_text="零参考线", annotation_position="top")
    fig.update_xaxes(title="系数（95% 置信区间）")
    fig.update_layout(height=max(320, 60 * len(coef) + 120))
    return apply_theme(fig, title="回归系数森林图（控制同主体后的相关关系）")
