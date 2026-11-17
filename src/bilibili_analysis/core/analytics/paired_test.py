"""同主体对照检验：Wilcoxon 配对检验 + UP主固定效应回归。

配对规则（工程默认，注释写明）：以 owner_mid 分组，每条 head 视频与
同 UP主 全部 control 视频的中位数配对；head 数不足 5 的 UP主 不参与并计数。

结论表述约束：只称「控制同主体后的相关关系」，禁止因果措辞。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import rankdata, wilcoxon
from statsmodels.stats.multitest import multipletests

from bilibili_analysis.core.db import get_snapshots, get_uppers, get_videos

# 默认检验特征：播放量与时长取 log（偏态），互动率为派生指标
DEFAULT_FEATURES = ("log_view", "log_duration", "engagement_rate")


def build_feature_table() -> pd.DataFrame:
    """构造特征表：视频元信息 + 最新快照统计 + 派生特征（log/互动率）。"""
    vids = get_videos()[["bvid", "owner_mid", "owner_name", "sample_group",
                         "duration", "title", "pubdate", "tname"]]
    snaps = get_snapshots()
    if snaps.empty:
        return pd.DataFrame()
    latest = snaps.sort_values("collect_time").groupby("bvid").tail(1)
    df = vids.merge(latest, on="bvid", how="inner")
    df["log_view"] = np.log1p(df["view"].astype(float))
    df["log_duration"] = np.log1p(df["duration"].astype(float))
    denom = df[["like", "coin", "fav", "share"]].astype(float).sum(axis=1)
    df["engagement_rate"] = np.where(df["view"] > 0, denom / df["view"].replace(0, np.nan), np.nan)
    return df


def _rank_biserial(diff: np.ndarray) -> float:
    """rank-biserial 效应量：r = (W+ − W−) / (W+ + W−)。"""
    nonzero = diff[diff != 0]
    if len(nonzero) == 0:
        return float("nan")
    ranks = rankdata(np.abs(nonzero))
    w_plus = ranks[nonzero > 0].sum()
    w_minus = ranks[nonzero < 0].sum()
    total = w_plus + w_minus
    return float((w_plus - w_minus) / total) if total else float("nan")


def paired_wilcoxon_one(feature: str, min_pairs_per_up: int = 5) -> dict:
    """单特征 Wilcoxon 配对检验：head vs 同 UP主 control 中位数。

    min_pairs_per_up：配对不足该值的 UP主 不参与并计数（工程默认 5）。
    """
    df = build_feature_table()
    rows: list[dict] = []
    skipped_ups = 0
    for mid, g in df.groupby("owner_mid"):
        head_vals = g[g["sample_group"] == "head"][feature].dropna()
        ctrl_vals = g[g["sample_group"] == "control"][feature].dropna()
        if len(ctrl_vals) == 0:
            continue
        if len(head_vals) < min_pairs_per_up:
            skipped_ups += 1
            continue
        ctrl_med = float(ctrl_vals.median())
        for v in head_vals:
            rows.append({"head": float(v), "control": ctrl_med, "mid": mid})
    pair_df = pd.DataFrame(rows)
    out = {"feature": feature, "n_pairs": len(pair_df),
           "n_uppers_used": pair_df["mid"].nunique() if len(pair_df) else 0,
           "skipped_ups": skipped_ups}
    if len(pair_df) < 5:
        out["note"] = "有效配对不足，未检验"
        return out
    stat, p = wilcoxon(pair_df["head"], pair_df["control"])
    out.update({
        "statistic": float(stat), "p_value": float(p),
        "rank_biserial": _rank_biserial(pair_df["head"].values - pair_df["control"].values),
        "median_head": float(pair_df["head"].median()),
        "median_control": float(pair_df["control"].median()),
        # 原始配对（head 值 / control 中位数 / mid），供页面差值分布图复用
        "pairs": pair_df[["head", "control", "mid"]],
    })
    return out


def paired_wilcoxon_table(features: tuple = DEFAULT_FEATURES) -> pd.DataFrame:
    """多特征配对检验表 + FDR 校正（BH）。"""
    results = [paired_wilcoxon_one(f) for f in features]
    df = pd.DataFrame(results)
    if "p_value" in df.columns:
        mask = df["p_value"].notna()
        if mask.sum() > 0:
            _, p_adj, _, _ = multipletests(df.loc[mask, "p_value"].values, method="fdr_bh")
            df.loc[mask, "p_fdr"] = p_adj
    return df


def fixed_effect_regression(df: pd.DataFrame | None = None) -> dict:
    """UP主固定效应回归：log(view+1) ~ 视频特征 + 控制变量 + UP主虚拟变量。

    输出系数表（系数/标准误/95%CI/t/p）、样本量、UP主数、组内 R²（within）。
    结论只能表述为「控制同主体后的相关关系」。
    """
    if df is None:
        df = build_feature_table()
    if df.empty:
        return {"note": "无数据"}
    data = df.merge(get_uppers()[["mid", "fans"]], left_on="owner_mid",
                    right_on="mid", how="left", suffixes=("", "_upper"))
    snaps = get_snapshots()
    last_time = pd.to_datetime(snaps["collect_time"]).max() if not snaps.empty else pd.Timestamp.now()
    pub = pd.to_datetime(data["pubdate"])
    data["days_since_pub"] = (last_time - pub).dt.days.clip(lower=0)
    data["title_len"] = data["title"].astype(str).str.len()
    data["has_digit"] = data["title"].astype(str).str.contains(r"\d").astype(int)
    data["has_question"] = data["title"].astype(str).str.contains("[?？]").astype(int)
    data["has_exclaim"] = data["title"].astype(str).str.contains("[!！]").astype(int)
    data["log_fans"] = np.log1p(data["fans"].astype(float))
    data["hour"] = pub.dt.hour
    data = data.dropna(subset=["log_view", "log_duration", "log_fans"])

    core_cols = ["log_duration", "title_len", "has_digit", "has_question",
                 "has_exclaim", "log_fans", "days_since_pub"]
    dummies = pd.get_dummies(data["owner_mid"], prefix="up", drop_first=True, dtype=float)
    X = pd.concat([data[core_cols].reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)
    y = data["log_view"].reset_index(drop=True)

    # 标准误按 owner_mid 聚类（cluster robust，提示词硬约束）
    model = sm.OLS(y, sm.add_constant(X)).fit(
        cov_type="cluster", cov_kwds={"groups": data["owner_mid"].values})
    # 组内 R²：对 y 与核心变量做 UP主 组内去均值后回归（固定效应 within 变换）
    grp = data.assign(_y=y.values)
    y_w = grp["_y"] - grp.groupby("owner_mid")["_y"].transform("mean")
    core_w = data[core_cols] - data.groupby("owner_mid")[core_cols].transform("mean")
    within = sm.OLS(y_w, sm.add_constant(core_w)).fit()

    coef = pd.DataFrame({
        "系数": model.params, "标准误": model.bse,
        "CI下限": model.conf_int()[0], "CI上限": model.conf_int()[1],
        "t值": model.tvalues, "p值": model.pvalues,
    }).round(4)
    core_coef = coef[coef.index.isin(["const"] + core_cols)]
    return {
        "coef_table": core_coef,
        "n_obs": int(model.nobs),
        "n_uppers": int(data["owner_mid"].nunique()),
        "r2": float(model.rsquared),
        "within_r2": float(within.rsquared),
        "coef_full": coef,
    }
