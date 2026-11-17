"""AI 提示词模板（集中管理，逐段中文注释）。

三类模板：
1. 局部解读 build_local_prompt：各分析页「AI 解读」按钮，一次解读一组图表数据；
2. 综合报告 build_report_prompt：AI 分析中心，汇总多模块数据生成报告；
3. 情感抽检 build_sentiment_check_prompt：选型实验的一致率参考（辅助，不替代人工标注）。

统一注入约束（所有模板强制执行，对齐论文口径）：
- 数据一律以结构化文本注入；图表截图不入 prompt（多模态不依赖）；
- 「只基于提供数据分析，禁止编造数字；数据不足要明说」；
- 结论口径只用「相关 / 伴随 / 差异」，禁止因果断言。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# 公共约束（注入每个 prompt 的开头）
# ---------------------------------------------------------------------------
_BASE_RULES = """你是一名严谨的数据分析助手。请严格遵守以下规则：
1. 只基于我提供的数据进行分析，禁止编造或推测数据中不存在的数字；
2. 数据缺失或样本量不足时，必须明确说「数据不足，无法得出可靠结论」，不要硬凑结论；
3. 描述变量间关系时，只允许使用「相关 / 伴随 / 存在差异」等表述，禁止使用
   「导致 / 使得 / 因为所以」等因果断言（本研究为观察性数据，只能说明相关）；
4. 用中文回答，分点输出，每个结论后面用括号标注所依据的数据（如「…（中位数 2.1 万）」）；
5. 快照类数据只能描述「观测期内的变化」，必须注明「首轮采集之前的历史不可知」。"""

# 各场景补充说明：告诉模型这组数据「是什么、看什么」
_SCENE_GUIDES = {
    "video_profile": (
        "以下是上榜视频（head）与同 UP主对照投稿（control）的画像数据。"
        "请关注：分区构成、播放量分布（对数尺度）、时长分布、发布时段集中区间、"
        "标题长度特征，以及 head 与 control 两个样本层的结构差异。"
    ),
    "paired_test": (
        "以下是控制同一 UP主 后，上榜视频与对照投稿的 Wilcoxon 配对检验结果。"
        "请关注：各特征的配对数、p 值（原始与 FDR 校正后）、rank-biserial 效应量大小与方向；"
        "效应量绝对值小于 0.1 视为可忽略，0.1~0.3 小，0.3~0.5 中，大于 0.5 大。"
    ),
    "regression": (
        "以下是 UP主固定效应回归结果（因变量 log(播放量+1)）。"
        "请关注：核心变量的系数方向、显著性、95% 置信区间是否跨越 0；"
        "组内 R² 反映控制 UP主 后特征仍能解释的差异比例。"
        "结论只能表述为「控制同主体后的相关关系」。"
    ),
    "upper_quadrant": (
        "以下是 UP主破圈四象限数据（X=粉丝量，Y=破圈度=播放中位数/粉丝）。"
        "请关注：四个象限的 UP主构成与数量对比、典型代表；"
        "粉丝为当前快照值，对老视频存在失真，需在结论中注明此局限。"
    ),
    "cluster": (
        "以下是 UP主 KMeans 聚类结果（标准化后的类中心）。"
        "请关注：各类在粉丝量、投稿规模、播放、破圈度上的差异，给出每类的简短命名；"
        "轮廓系数用于说明聚类结构清晰度。"
    ),
    "text_analysis": (
        "以下是评论弹幕文本分析数据（高频词、媒介对比、进度分布、趋同度案例）。"
        "请关注：弹幕与热评的高频词差异反映的媒介特征（弹幕短平快、评论更长更完整）、"
        "趋同度案例反映的集体情绪时刻；进度分布仅基于 ratio 达标视频。"
    ),
    "snapshot": (
        "以下是统计字段快照数据（相邻时点增量 Δ 与窗口累计增量）。"
        "横轴为观测轮次；首轮采集之前的历史不可知，禁止推断发布初期的增长情况。"
    ),
}

_OUTPUT_RULES = "请基于上述数据输出 4~6 条要点解读，每点一句话结论 + 括号内的数据依据。"


# ---------------------------------------------------------------------------
# 数据序列化工具（不依赖 tabulate，手写 markdown 表格）
# ---------------------------------------------------------------------------
def _df_to_markdown(df: pd.DataFrame, max_rows: int = 15) -> str:
    """DataFrame 转紧凑 markdown 表格（超长截断，防止 prompt 膨胀）。"""
    show = df.head(max_rows)
    cols = [str(c) for c in show.columns]
    lines = ["| " + " | ".join(cols) + " |",
             "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in show.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.values) + " |")
    if len(df) > max_rows:
        lines.append(f"（仅展示前 {max_rows} 行，共 {len(df)} 行）")
    return "\n".join(lines)


def _value_to_text(value: Any, max_rows: int = 15) -> str:
    """把 DataFrame / Series / dict / 其他对象转成可注入的结构化文本。"""
    if isinstance(value, pd.DataFrame):
        return _df_to_markdown(value, max_rows)
    if isinstance(value, pd.Series):
        return _df_to_markdown(value.reset_index(), max_rows)
    if isinstance(value, dict):
        return "\n".join(f"- {k}: {v}" for k, v in value.items())
    return str(value)


def _assemble(scene: str, tables: dict[str, Any], output_rules: str) -> str:
    """组装 prompt：公共约束 → 场景说明 → 数据块 → 输出要求。"""
    parts = [_BASE_RULES, "", _SCENE_GUIDES.get(scene, "请基于以下数据进行分析。"), ""]
    for name, value in tables.items():
        parts.append(f"### 数据：{name}")
        parts.append(_value_to_text(value))
        parts.append("")
    parts.append(output_rules)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 模板一：局部解读（各分析页「AI 解读」按钮）
# ---------------------------------------------------------------------------
def build_local_prompt(scene: str, tables: dict[str, Any]) -> str:
    """局部解读模板。

    参数：
        scene：场景名（video_profile / paired_test / regression / upper_quadrant /
               cluster / text_analysis / snapshot），决定场景提示语。
        tables：{数据名称: DataFrame/Series/dict}，将逐一序列化注入。
    """
    return _assemble(scene, tables, _OUTPUT_RULES)


# ---------------------------------------------------------------------------
# 模板二：综合报告（AI 分析中心）
# ---------------------------------------------------------------------------
def build_report_prompt(sections: dict[str, Any]) -> str:
    """综合报告模板：多模块汇总数据 → 一份结构化研究报告。

    参数：
        sections：{模块名: 数据}，如 {"全局概况": {...}, "配对检验": DataFrame, ...}
    """
    rules = (
        "请基于以下多个模块的数据，输出一份结构化中文报告："
        "1) 总体概况（样本结构、数据覆盖）；"
        "2) 关键发现 3~5 条（每条标注数据依据与所在模块）；"
        "3) 数据局限与解读边界（样本量、快照口径、ratio 剔除、粉丝失真等）；"
        "4) 后续分析建议。全文使用「相关/伴随」口径，禁止因果断言。"
    )
    return _assemble("综合报告", sections, rules)


# ---------------------------------------------------------------------------
# 模板三：情感抽检校验（选型实验的一致率参考）
# ---------------------------------------------------------------------------
def build_sentiment_check_prompt(pairs: list[tuple[str, str]]) -> str:
    """情感抽检模板：给模型若干（评论文本, 工具判定）对，要求独立判断。

    返回的模型判定可与人工标注、工具判定计算一致率，作为选型实验的第三方参考。
    注意：此模板不替代人工标注，仅作辅助校验（提示词口径）。
    """
    rules = (
        "以下每行是一条 B站评论与其 sentiment 字段的当前取值。请你独立判断每条评论"
        "的情感倾向（正 / 中 / 负），逐行输出「序号: 你的判定 - 一句话理由」。"
        "判断标准：正面（赞美/支持/积极情绪）、负面（批评/嘲讽/消极情绪）、"
        "中性（陈述/疑问/无关情绪）。不要参考或迎合已有取值，独立判断。"
    )
    lines = [f"{i + 1}. 评论：{text[:100]} | 当前字段值：{label}"
             for i, (text, label) in enumerate(pairs)]
    return f"{_BASE_RULES}\n\n{rules}\n\n" + "\n".join(lines)
