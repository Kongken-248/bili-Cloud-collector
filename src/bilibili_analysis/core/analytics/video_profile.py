"""视频画像分析（前置）。

输出各分区播放量分布（log）、时长分布、发布时段热力、标题长度分布，
head 与 control 分层展示。纯数据聚合，不含界面代码。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bilibili_analysis.core.db import get_videos


def view_distribution() -> pd.DataFrame:
    """各分区播放量分布（含 log10，供 log 轴图表），head/control 分层。"""
    df = get_videos()
    df = df[df["latest_view"].notna() & (df["latest_view"] > 0)].copy()
    df["log_view"] = np.log10(df["latest_view"].astype(float))
    return df[["bvid", "tname", "sample_group", "latest_view", "log_view", "duration"]]


def duration_distribution() -> pd.DataFrame:
    """时长分布（秒），head/control 分层。"""
    df = get_videos()
    out = df[df["duration"].notna()].copy()
    return out[["bvid", "tname", "sample_group", "duration"]]


def pub_hour_heatmap() -> pd.DataFrame:
    """发布时段热力：星期 × 小时的投稿计数（0=周一）。"""
    df = get_videos()
    df = df[df["pubdate"].notna()].copy()
    dt = pd.to_datetime(df["pubdate"])
    df["weekday"] = dt.dt.dayofweek
    df["hour"] = dt.dt.hour
    return df.groupby(["weekday", "hour"]).size().reset_index(name="count")


def title_length_distribution() -> pd.DataFrame:
    """标题长度分布（字符数），head/control 分层。"""
    df = get_videos()
    df = df[df["title"].notna()].copy()
    df["title_len"] = df["title"].astype(str).str.len()
    return df[["bvid", "sample_group", "title_len"]]


def profile_summary() -> dict:
    """画像汇总表：head/control 各自的播放、时长、标题长度描述统计。"""
    df = get_videos()
    rows = []
    for group, g in df.groupby("sample_group"):
        views = g["latest_view"].dropna()
        rows.append({
            "sample_group": group,
            "视频数": len(g),
            "播放中位数": float(views.median()) if len(views) else None,
            "播放均值": float(views.mean()) if len(views) else None,
            "时长中位数(秒)": float(g["duration"].median()) if g["duration"].notna().any() else None,
            "标题长度中位数": float(g["title"].astype(str).str.len().median()) if g["title"].notna().any() else None,
        })
    return {"table": pd.DataFrame(rows), "heatmap": pub_hour_heatmap()}
