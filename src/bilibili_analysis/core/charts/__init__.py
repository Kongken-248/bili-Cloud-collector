"""图表层包：全系统 Plotly 图表函数唯一归属（模块三）。

视觉唯一真源在 theme.py（F2 纸白追番站色值与主题）。
输入一律为 analytics 子包的结构化输出，本层只做展示、不做数据聚合。
"""

from bilibili_analysis.core.charts.overview import (
    delta_bar,
    partition_distribution,
    view_cum_fig,
)
from bilibili_analysis.core.charts.text import (
    media_len_fig,
    media_words_fig,
    progress_fig,
    sentiment_partition_fig,
    top_words_bar,
    wordcloud_html,
)
from bilibili_analysis.core.charts.theme import (
    apply_theme,
    blank_fig,
    color_for_partition,
    counts_bar,
    wordcloud_html as wordcloud,
)
from bilibili_analysis.core.charts.upper import (
    centers_heatmap_fig,
    fans_hist_fig,
    k_score_fig,
    quadrant_scatter_fig,
    up_post_fig,
)
from bilibili_analysis.core.charts.video import (
    duration_hist_fig,
    forest_fig,
    pair_diff_fig,
    pub_heatmap_fig,
    title_len_fig,
    view_dist_fig,
)

__all__ = [
    # theme
    "apply_theme", "blank_fig", "color_for_partition", "counts_bar", "wordcloud",
    # overview
    "partition_distribution", "view_cum_fig", "delta_bar",
    # video
    "view_dist_fig", "duration_hist_fig", "pub_heatmap_fig", "title_len_fig",
    "pair_diff_fig", "forest_fig",
    # upper
    "fans_hist_fig", "up_post_fig", "quadrant_scatter_fig",
    "k_score_fig", "centers_heatmap_fig",
    # text
    "top_words_bar", "media_len_fig", "media_words_fig", "progress_fig",
    "sentiment_partition_fig", "wordcloud_html",
]
