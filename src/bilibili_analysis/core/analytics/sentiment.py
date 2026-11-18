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
from bilibili_analysis.core.db import get_comments, get_connection, get_danmaku

DATA_DIR = PROJECT_ROOT / "data"
# 标注文件按来源分开：comments 回填表字段，danmaku 另存结果（数据字典口径）
_ANNOTATION_FILES = {
    "comments": DATA_DIR / "sentiment_annotation_comments.csv",
    "danmaku": DATA_DIR / "sentiment_annotation_danmaku.csv",
}


def export_annotation_sample(source: str = "comments", n: int = 300, seed: int = 42) -> Path:
    """按 bvid 分层比例抽样导出标注样本，供人工标注。

    source：comments（一级热评）或 danmaku（弹幕正文）；n 目标样本量（提示词 200–300）。
    纯比例抽样（小视频按占比可能 0 条），总量 ≈ n，避免每视频强制 1 条导致样本膨胀。
    """
    df = get_comments() if source == "comments" else get_danmaku()
    if df.empty:
        raise ValueError(f"{source} 表为空，请先运行采集")
    per = (n * df.groupby("bvid").size() / len(df)).round().astype(int)
    parts = [g.sample(min(len(g), per[bvid]), random_state=seed)
             for bvid, g in df.groupby("bvid") if per[bvid] > 0]
    sample = pd.concat(parts)
    text_col = "content"
    out = sample[["rpid" if source == "comments" else "dmid", "bvid", text_col]].copy()
    out.columns = ["id", "bvid", "content"]
    out["label"] = ""  # 人工标注列：正 / 中 / 负
    path = _ANNOTATION_FILES[source]
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def import_annotation(source: str = "comments") -> pd.DataFrame:
    """读回人工标注结果（label 列取值为 正/中/负）。"""
    return pd.read_csv(_ANNOTATION_FILES[source], encoding="utf-8-sig")


def _score_with_tool(texts: list[str], tool: str) -> list[str] | None:
    """用指定工具打三分类（正/中/负）；工具未安装/不可用返回 None。

    llm 分支：分批（每批 30 条）调真实大模型独立判断，作为选型对比工具之一。
    """
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
    if tool == "llm":
        import re

        from bilibili_analysis.core.llm import chat

        out: list[str] = []
        batch_size = 30
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            lines = "\n".join(f"{j + 1}. {str(t)[:80]}" for j, t in enumerate(batch))
            prompt = (
                "你是情感标注员。对下列每条 B站评论/弹幕独立判断情感倾向（正/中/负）。"
                "判断标准：正面=赞美/支持/积极情绪；负面=批评/嘲讽/消极情绪；"
                "中性=陈述/疑问/无关情绪。\n"
                "严格按「序号: 判定」逐行输出，不要任何多余文字：\n" + lines
            )
            r = chat(prompt, temperature=0.0, scene="情感选型-llm对比")
            if not r.ok:
                return None
            mapping = {}
            for line in r.content.splitlines():
                m = re.match(r"\s*(\d+)\s*[:：.]\s*(正|中|负)", line)
                if m:
                    mapping[int(m.group(1))] = m.group(2)
            out.extend(mapping.get(j + 1, "中") for j in range(len(batch)))
        return out
    return None  # cemotion / PaddleNLP 等本地模型按选型实验扩展


def compare_tools(source: str = "comments", min_labeled: int = 30) -> pd.DataFrame:
    """各工具在人工标注集上的准确率与宏 F1；工具未安装则跳过并留痕。"""
    labeled = import_annotation(source)
    labeled = labeled[labeled["label"].isin(["正", "中", "负"])]
    if len(labeled) < min_labeled:
        raise ValueError(f"有效标注仅 {len(labeled)} 条（需 ≥{min_labeled}），请先完成人工标注")
    from sklearn.metrics import accuracy_score, f1_score

    rows = []
    for tool in ("snownlp", "cemotion", "llm"):
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
