"""分析聚合逻辑子包。

纯 pandas / statsmodels / scipy / scikit-learn，不含界面代码。
每个函数返回 DataFrame/dict，输出结构化结果表供图表层与 AI 解读复用。

模块划分：
- video_profile：视频画像（前置）
- paired_test：Wilcoxon 配对检验 + UP主固定效应回归
- upper_analysis：破圈四象限 + KMeans 聚类画像
- text_analysis：高频词/词云、媒介对比、进度直方图、弹幕趋同度
- sentiment：情感选型实验（先实验后全量）
- snapshot_desc：快照轻量描述（B 级）
"""

from bilibili_analysis.core.analytics.paired_test import (
    build_feature_table,
    fixed_effect_regression,
    paired_wilcoxon_one,
    paired_wilcoxon_table,
)
from bilibili_analysis.core.analytics.snapshot_desc import delta_summary, view_cum_curve
from bilibili_analysis.core.analytics.text_analysis import (
    danmaku_convergence,
    media_compare,
    progress_histogram,
    top_words,
)
from bilibili_analysis.core.analytics.upper_analysis import breakout_quadrant, cluster_profile
from bilibili_analysis.core.analytics.video_profile import (
    duration_distribution,
    profile_summary,
    pub_hour_heatmap,
    title_length_distribution,
    view_distribution,
)

__all__ = [
    "build_feature_table", "fixed_effect_regression",
    "paired_wilcoxon_one", "paired_wilcoxon_table",
    "delta_summary", "view_cum_curve",
    "danmaku_convergence", "media_compare", "progress_histogram", "top_words",
    "breakout_quadrant", "cluster_profile",
    "duration_distribution", "profile_summary", "pub_hour_heatmap",
    "title_length_distribution", "view_distribution",
]
