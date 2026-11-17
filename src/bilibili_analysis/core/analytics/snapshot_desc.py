"""快照轻量描述（数据字典 B 级）。

横轴 = 观测轮次；仅描述，不建模、不预测；
图注必须写「首轮之前历史不可知」；
禁止「发布后天数 × 播放量」曲线与任何增长建模。
"""

from __future__ import annotations

import pandas as pd

from bilibili_analysis.core.db import get_delta_table, get_snapshots

_METRICS = ["view", "like", "coin", "fav", "share", "reply", "danmaku"]


def delta_summary() -> dict:
    """Δ 汇总：各指标相邻时点增量的描述统计 + 实际间隔分布。"""
    dt = get_delta_table()
    if dt.empty:
        return {"note": "快照不足 2 轮，无法计算 Δ（首轮 T0 之后才可算）"}
    cols = [f"{m}_delta" for m in _METRICS if f"{m}_delta" in dt.columns]
    return {"delta_stats": dt[cols].describe().round(1),
            "interval_stats": dt["interval_sec"].describe().round(0),
            "n_rows": len(dt)}


def view_cum_curve() -> pd.DataFrame:
    """窗口累计增量曲线数据：横轴=观测轮次（round 从 0 起）。

    图注要求：首轮之前历史不可知；view_cum = view(t) − view(T0)。
    """
    snaps = get_snapshots()
    snaps = snaps.sort_values(["bvid", "collect_time"]).copy()
    snaps["round"] = snaps.groupby("bvid").cumcount()
    t0 = snaps.groupby("bvid")["view"].transform("first")
    snaps["view_cum"] = snaps["view"].astype(float) - t0.astype(float)
    return snaps[["bvid", "round", "collect_time", "view_cum"]]
