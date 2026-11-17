"""评论弹幕文本分析：高频词/词云、媒介对比、进度分布直方图、弹幕趋同度。

口径约束（数据字典）：
- 进度直方图仅用 ratio 达标视频，剔除清单留痕；不做峰值检测；
- 跨视频弹幕比较只用「视频内占比」，不做绝对条数比较；
- 趋同度按 10 秒窗口（配置项）计算 1 − distinct/count。
"""

from __future__ import annotations

import re
from collections import Counter

import numpy as np
import pandas as pd

from bilibili_analysis.core.config import (
    DANMAKU_PROGRESS_BINS,
    DANMAKU_RATIO_THRESHOLD,
    DANMAKU_SIMILARITY_WINDOW,
)
from bilibili_analysis.core.db import (
    get_comments,
    get_danmaku,
    get_danmaku_ratio,
    get_videos,
)

# 内置精简中文停用词（工程默认，可后续扩充外部词表）
STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "这个", "那个", "什么", "怎么", "还是", "但是", "所以", "因为",
    "啊", "吧", "吗", "呢", "哦", "嗯", "哈哈", "哈哈哈", "hhhh", "hhhhh",
}


def tokenize(texts, top_n: int = 50) -> list[tuple[str, int]]:
    """jieba 分词 + 停用词/单字/纯数字过滤，返回 Top 词 [(词, 频次)]。"""
    import jieba

    counter: Counter = Counter()
    for t in texts:
        if not t:
            continue
        for w in jieba.cut(str(t)):
            w = w.strip()
            if len(w) < 2 or w in STOPWORDS or re.fullmatch(r"[\d\W_]+", w):
                continue
            counter[w] += 1
    return counter.most_common(top_n)


def top_words(source: str = "danmaku", bvid: str | None = None, top_n: int = 50):
    """高频词/词云数据：source 为 danmaku（弹幕）或 comments（一级热评）。"""
    df = get_danmaku(bvid) if source == "danmaku" else get_comments(bvid)
    return tokenize(df["content"].dropna().tolist(), top_n)


def media_compare(bvid: str) -> dict:
    """弹幕/评论媒介对比（同视频两侧）：文本长度分布 + Top 词重合度。

    口径注明：一级热评（主楼） vs 弹幕，非全部评论。
    """
    dan = get_danmaku(bvid)
    com = get_comments(bvid)
    dan_len = dan["content"].astype(str).str.len()
    com_len = com["content"].astype(str).str.len()
    dan_top = dict(tokenize(dan["content"].tolist(), 100))
    com_top = dict(tokenize(com["content"].tolist(), 100))
    overlap = sorted(set(dan_top) & set(com_top))
    return {
        "danmaku_len": dan_len.describe().round(1).to_dict(),
        "comment_len": com_len.describe().round(1).to_dict(),
        "danmaku_top": list(dan_top.items())[:20],
        "comment_top": list(com_top.items())[:20],
        "top_overlap": overlap[:20],
        "overlap_ratio": round(len(overlap) / max(len(set(dan_top) | set(com_top)), 1), 3),
    }


def progress_histogram(bins: int = DANMAKU_PROGRESS_BINS) -> dict:
    """进度分布直方图：progress/duration 分箱，视频内占比归一化后跨视频求均值。

    仅用 ratio 达标视频（阈值配置项），剔除清单留痕；不做峰值检测。
    """
    ratio_df = get_danmaku_ratio()
    if ratio_df.empty:
        return {"note": "无弹幕对账数据", "mean_curve": pd.Series(dtype=float)}
    ok = ratio_df.groupby("bvid")["ratio"].max()
    ok_bvids = ok[ok >= DANMAKU_RATIO_THRESHOLD].index.tolist()
    excluded = ok[ok < DANMAKU_RATIO_THRESHOLD].index.tolist()
    dan = get_danmaku()
    dan = dan[dan["bvid"].isin(ok_bvids) & dan["progress"].notna()]
    vids = get_videos()[["bvid", "duration"]]
    merged = dan.merge(vids, on="bvid", how="left")
    merged = merged[merged["duration"] > 0].copy()
    merged["pos"] = (merged["progress"] / merged["duration"]).clip(0, 1)
    merged["bin"] = (merged["pos"] * bins).astype(int).clip(0, bins - 1)
    per_video = merged.groupby(["bvid", "bin"]).size().reset_index(name="n")
    per_video["share"] = per_video["n"] / per_video.groupby("bvid")["n"].transform("sum")
    mean_curve = per_video.groupby("bin")["share"].mean().round(4)
    return {"mean_curve": mean_curve, "bins": bins,
            "n_videos_used": len(ok_bvids), "excluded_bvids": excluded}


def danmaku_convergence(bvid: str | None = None,
                        window: int = DANMAKU_SIMILARITY_WINDOW,
                        min_count: int = 5) -> dict:
    """弹幕趋同度：window 秒窗口内 1 − distinct(content)/count。

    高弹幕量窗口（count ≥ min_count）按趋同度分型：
    ≥0.5 为共鸣型（重复刷屏），否则为争议型（内容各异）——工程默认阈值。
    """
    dan = get_danmaku(bvid)
    dan = dan[dan["progress"].notna()].copy()
    if dan.empty:
        return {"note": "无弹幕数据"}
    dan["win"] = (dan["progress"] // window).astype(int)
    g = dan.groupby(["bvid", "win"]).agg(
        count=("content", "size"), distinct=("content", "nunique")).reset_index()
    g["convergence"] = (1 - g["distinct"] / g["count"]).round(4)
    high = g[g["count"] >= min_count].copy()
    high["type"] = np.where(high["convergence"] >= 0.5, "共鸣型", "争议型")

    # 典型案例：每类型取趋同度最极端的窗口，附代表弹幕（窗口位置 + 内容）
    cases: list[dict] = []
    for t, sub in high.groupby("type"):
        pick = sub.nlargest(3, "convergence" if t == "共鸣型" else "count")
        for _, row in pick.iterrows():
            win_dan = dan[(dan["bvid"] == row["bvid"]) & (dan["win"] == row["win"])]
            top = win_dan["content"].value_counts().head(3).index.tolist()
            cases.append({"type": t, "bvid": row["bvid"], "win": int(row["win"]),
                          "窗口位置(秒)": int(row["win"] * window),
                          "count": int(row["count"]),
                          "convergence": float(row["convergence"]),
                          "代表弹幕": top})
    return {"window_sec": window, "stats": g[["count", "distinct", "convergence"]]
            .describe().round(3), "high_windows": high,
            "cases": cases}
