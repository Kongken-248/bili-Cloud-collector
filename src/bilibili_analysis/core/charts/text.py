"""评论弹幕分析图表：高频词 / 媒介对比 / 进度分布直方图 / 情感分布。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from bilibili_analysis.core.charts.theme import (
    CONTROL_COLOR,
    HEAD_COLOR,
    MUTED,
    PINK,
    PINK_SOFT,
    apply_theme,
    color_for_partition,
    wordcloud_html,
)


def top_words_bar(words: list[tuple[str, int]], color: str = PINK,
                  title: str = "高频词 Top 20") -> go.Figure:
    """高频词横向条形图；输入 top_words() 的 [(词, 频次)]。"""
    words = words[:20]
    fig = go.Figure(go.Bar(
        x=[c for _, c in reversed(words)],
        y=[w for w, _ in reversed(words)], orientation="h", marker_color=color,
        hovertemplate="%{y}：%{x} 次<extra></extra>"))
    fig.update_xaxes(title="出现次数")
    return apply_theme(fig, title=title)


def media_len_fig(danmaku_lengths: list, comment_lengths: list) -> go.Figure:
    """媒介对比组图之一：弹幕 vs 一级热评 文本长度分布叠加直方图。"""
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=danmaku_lengths, name="弹幕", opacity=0.75,
                               marker_color=HEAD_COLOR, nbinsx=30))
    fig.add_trace(go.Histogram(x=comment_lengths, name="一级热评", opacity=0.75,
                               marker_color=CONTROL_COLOR, nbinsx=30))
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(title="文本长度（字符）")
    fig.update_yaxes(title="条数")
    return apply_theme(fig, title="媒介对比：文本长度分布（一级热评 vs 弹幕）")


def media_words_fig(danmaku_top: list, comment_top: list) -> go.Figure:
    """媒介对比组图之二：两侧 Top 词频对比（分组条形，同词对齐）。"""
    dan = dict(danmaku_top)
    com = dict(comment_top)
    common = sorted((set(dan) | set(com)) & (set(dan) | set(com)),
                    key=lambda w: -(dan.get(w, 0) + com.get(w, 0)))[:15]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="弹幕", x=common, y=[dan.get(w, 0) for w in common],
                         marker_color=HEAD_COLOR))
    fig.add_trace(go.Bar(name="一级热评", x=common, y=[com.get(w, 0) for w in common],
                         marker_color=CONTROL_COLOR))
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="出现次数")
    return apply_theme(fig, title="媒介对比：两侧高频词（Top 词差异）")


def progress_fig(progress: dict) -> go.Figure:
    """进度分布直方图：均值柱 + 分区注意力曲线（仅 ratio 达标视频）。"""
    curve = progress["mean_curve"]
    bins = progress.get("bins", 20)
    labels = [f"{i / bins:.0%}-{(i + 1) / bins:.0%}" for i in range(len(curve))]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=curve.values, name="全样本均值",
                         marker_color=PINK_SOFT,
                         hovertemplate="%{x}：%{y:.2%}<extra></extra>"))
    for tname, pcurve in progress.get("partition_curves", {}).items():
        y = [float(pcurve.get(i, 0.0)) for i in range(len(curve))]
        fig.add_trace(go.Scatter(x=labels, y=y, name=tname, mode="lines+markers",
                                 line=dict(color=color_for_partition(tname), width=2),
                                 hovertemplate=f"{tname} %{{x}}：%{{y:.2%}}<extra></extra>"))
    fig.update_yaxes(title="视频内弹幕占比（跨视频均值）", tickformat=".0%")
    fig.update_xaxes(title="视频进度分箱")
    return apply_theme(fig, height=440,
                       title="进度分布直方图与分区注意力曲线（仅 ratio 达标视频）")


def sentiment_partition_fig(sent_df: pd.DataFrame) -> go.Figure:
    """情感分布分区对比：分区 × 三分类堆叠柱；输入含 tname/sentiment 列。"""
    cross = (sent_df.groupby(["tname", "sentiment"]).size().unstack(fill_value=0))
    colors = {"正": HEAD_COLOR, "中": MUTED, "负": CONTROL_COLOR}
    fig = go.Figure()
    for label in ("正", "中", "负"):
        if label in cross.columns:
            fig.add_trace(go.Bar(name=label, x=cross.index, y=cross[label],
                                 marker_color=colors[label]))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="评论数")
    return apply_theme(fig, title="情感分布分区对比（选定工具全量打分）")


__all__ = ["top_words_bar", "media_len_fig", "media_words_fig", "progress_fig",
           "sentiment_partition_fig", "wordcloud_html"]
