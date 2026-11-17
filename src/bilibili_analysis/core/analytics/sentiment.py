"""情感分析选型实验框架（提示词硬约束：先实验、后全量）。

流程约束：
1. 分层抽样导出标注样本 → 人工标注（正/中/负）→ 回填；
2. 多工具在标注集上对比准确率/F1，选型结论落盘；
3. 选定工具后才能全量打分回填 comments.sentiment。
未完成选型实验前，禁止默认 SnowNLP 出全量结果。

工具按需导入：SnowNLP / Cemotion / 本地预训练模型；未安装则跳过并提示。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bilibili_analysis.core.config import PROJECT_ROOT
from bilibili_analysis.core.db import get_comments, get_connection

DATA_DIR = PROJECT_ROOT / "data"
ANNOTATION_FILE = DATA_DIR / "sentiment_annotation.csv"
SELECTION_FILE = DATA_DIR / "sentiment_selection.csv"


def export_annotation_sample(n: int = 200, seed: int = 42) -> Path:
    """按 bvid 分层抽样导出标注样本（每视频按占比分配），供人工标注。

    n：目标样本量（提示词 200–300 条）；返回标注文件路径。
    """
    com = get_comments()
    if com.empty:
        raise ValueError("comments 表为空，请先运行评论采集")
    per = (n * com.groupby("bvid").size() / len(com)).round().astype(int).clip(lower=1)
    parts = [g.sample(min(len(g), per[bvid]), random_state=seed)
             for bvid, g in com.groupby("bvid")]
    sample = pd.concat(parts)
    out = sample[["rpid", "bvid", "content"]].copy()
    out["label"] = ""  # 人工标注列：正 / 中 / 负
    ANNOTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(ANNOTATION_FILE, index=False, encoding="utf-8-sig")
    return ANNOTATION_FILE


def import_annotation(path: Path = ANNOTATION_FILE) -> pd.DataFrame:
    """读回人工标注结果（label 列取值为 正/中/负）。"""
    return pd.read_csv(path, encoding="utf-8-sig")


def _score_with_tool(texts: list[str], tool: str) -> list[str] | None:
    """用指定工具打三分类（正/中/负）；工具未安装返回 None。"""
    if tool == "snownlp":
        try:
            from snownlp import SnowNLP
        except ImportError:
            return None
        out = []
        for t in texts:
            s = SnowNLP(str(t)).sentiments
            out.append("正" if s > 0.6 else ("负" if s < 0.4 else "中"))
        return out
    return None  # cemotion / 预训练模型按选型实验扩展


def compare_tools(path: Path = ANNOTATION_FILE, min_labeled: int = 30) -> pd.DataFrame:
    """各工具在人工标注集上的准确率与宏 F1；工具未安装则跳过并留痕。"""
    labeled = import_annotation(path)
    labeled = labeled[labeled["label"].isin(["正", "中", "负"])]
    if len(labeled) < min_labeled:
        raise ValueError(f"有效标注仅 {len(labeled)} 条（需 ≥{min_labeled}），请先完成人工标注")
    from sklearn.metrics import accuracy_score, f1_score

    rows = []
    for tool in ("snownlp", "cemotion"):
        preds = _score_with_tool(labeled["content"].tolist(), tool)
        if preds is None:
            rows.append({"tool": tool, "accuracy": None, "macro_f1": None,
                         "note": "工具未安装，跳过"})
            continue
        rows.append({"tool": tool,
                     "accuracy": round(accuracy_score(labeled["label"], preds), 4),
                     "macro_f1": round(f1_score(labeled["label"], preds, average="macro"), 4),
                     "note": ""})
    return pd.DataFrame(rows)


def apply_sentiment(tool: str) -> int:
    """选定工具全量打分并回填 comments.sentiment（选型实验完成后才允许调用）。"""
    com = get_comments()
    preds = _score_with_tool(com["content"].tolist(), tool)
    if preds is None:
        raise ValueError(f"工具 {tool} 未安装或不可用，禁止回填")
    conn = get_connection()
    try:
        conn.executemany("UPDATE comments SET sentiment=? WHERE rpid=?",
                         list(zip(preds, com["rpid"])))
        conn.commit()
    finally:
        conn.close()
    SELECTION_FILE.write_text(f"selected_tool,{tool}\n", encoding="utf-8")
    return len(com)
