"""UP主分析：破圈四象限 + KMeans 聚类画像。

破圈度 = view / fans（fans=0 或缺失剔除并计数）；粉丝为当前快照值，
对老视频存在失真，结论中必须注明（数据字典 C 级约束）。
聚类固定随机种子保证可复现；K 由肘部（inertia）+ 轮廓系数双依据确定。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from bilibili_analysis.core.db import get_uppers, get_videos

RANDOM_SEED = 42  # 固定随机种子（结果可复现）


def upper_stats() -> pd.DataFrame:
    """UP主 级统计表：fans、投稿数、head 播放中位数、破圈度、代表视频。"""
    vids = get_videos()
    uppers = get_uppers()
    head = vids[vids["sample_group"] == "head"]
    stats = head.groupby("owner_mid").agg(
        median_view=("latest_view", "median"), head_count=("bvid", "size"))
    ctrl_count = vids[vids["sample_group"] == "control"].groupby("owner_mid").size()\
        .rename("control_count")
    df = uppers.set_index("mid").join(stats).join(ctrl_count).reset_index()
    # 代表视频：head 中播放量最高的视频标题（四象限悬停展示用）
    top_v = (head.dropna(subset=["latest_view"])
             .sort_values("latest_view").groupby("owner_mid").tail(1)
             .set_index("owner_mid")["title"].rename("top_video"))
    df = df.join(top_v, on="mid")
    # 破圈度：view / fans；fans 缺失或 ≤0 剔除并计数（不填 0 防除零）
    df["excluded_no_fans"] = df["fans"].isna() | (df["fans"] <= 0)
    df["breakout"] = np.where(df["excluded_no_fans"], np.nan,
                              df["median_view"] / df["fans"].replace(0, np.nan))
    return df


def breakout_quadrant() -> dict:
    """破圈四象限：X=粉丝量、Y=破圈度，分界线取中位数（工程默认）。

    返回分组表、分界线、剔除计数、各象限统计与代表 UP主。
    """
    df = upper_stats()
    valid = df.dropna(subset=["breakout"]).dropna(subset=["fans"]).copy()
    excluded = int(df["excluded_no_fans"].sum())
    if valid.empty:
        return {"note": "无有效 UP主（fans 全部缺失或为 0）", "excluded_no_fans": excluded}
    x_split, y_split = float(valid["fans"].median()), float(valid["breakout"].median())

    def quad(r) -> str:
        high_fans = r["fans"] >= x_split
        high_break = r["breakout"] >= y_split
        if high_fans and high_break:
            return "头部高破圈"
        if high_fans:
            return "头部低破圈"
        return "小身高破圈" if high_break else "小身低破圈"

    valid["quadrant"] = valid.apply(quad, axis=1)
    summary = valid.groupby("quadrant").agg(
        UP主数=("mid", "size"), 破圈度中位数=("breakout", "median"),
        粉丝中位数=("fans", "median")).reset_index()
    reps = valid.sort_values("breakout", ascending=False).groupby("quadrant").head(3)
    return {"table": valid[["mid", "name", "fans", "median_view", "breakout",
                            "quadrant", "top_video"]],
            "x_split": x_split, "y_split": y_split, "excluded_no_fans": excluded,
            "summary": summary, "representatives": reps}


def cluster_profile(k_min: int = 2, k_max: int = 8) -> dict:
    """KMeans 聚类画像：肘部 + 轮廓系数定 K，输出类中心对比与代表 UP主。

    特征（数据可得子集）：log 粉丝、log 投稿数、log head 播放中位数、破圈度。
    """
    df = upper_stats()
    data = df.dropna(subset=["fans", "archive_count", "median_view", "breakout"]).copy()
    if len(data) < 4:
        return {"note": f"有效样本仅 {len(data)} 个，不足以聚类"}
    feats = ["log_fans", "log_archive", "log_view", "breakout"]
    data["log_fans"] = np.log1p(data["fans"].astype(float))
    data["log_archive"] = np.log1p(data["archive_count"].astype(float))
    data["log_view"] = np.log1p(data["median_view"].astype(float))
    X_std = StandardScaler().fit_transform(data[feats].values)
    k_max = min(k_max, len(data) - 1)  # 轮廓系数要求 k ≤ n-1
    scores = []
    for k in range(k_min, k_max + 1):
        km = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init=10).fit(X_std)
        sil = silhouette_score(X_std, km.labels_) if len(set(km.labels_)) > 1 else -1.0
        scores.append({"k": k, "inertia": round(float(km.inertia_), 2),
                       "silhouette": round(float(sil), 4)})
    score_df = pd.DataFrame(scores)
    best_k = int(score_df.loc[score_df["silhouette"].idxmax(), "k"])
    km = KMeans(n_clusters=best_k, random_state=RANDOM_SEED, n_init=10).fit(X_std)
    data["cluster"] = km.labels_
    centers = pd.DataFrame(km.cluster_centers_, columns=feats).round(3)
    reps = data.groupby("cluster").apply(
        lambda g: g.nlargest(3, "median_view")[["name", "median_view"]]).reset_index()
    return {"k_scores": score_df, "best_k": best_k, "centers": centers,
            "members": data[["mid", "name", "cluster"] + feats], "representatives": reps}
