"""清洗入库脚本。

读取 data/raw/ 原始 JSON，按清洗规则写入 videos / uppers 表，
并对 danmaku / comments 表做异常时间戳清洗，打印清洗前后统计对比。
注意：snapshots 表唯一写入入口是 snapshot.py，clean.py 不写它。

字段口径唯一真源：docs/数据字典.md。

用法：
    python -m bilibili_analysis.scripts.clean
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime

from bilibili_analysis.core.config import PARTITIONS, RAW_DIR
from bilibili_analysis.core.db import get_connection
from bilibili_analysis.scripts._common import log, now_str


# ---------------------------------------------------------------------------
# 清洗工具
# ---------------------------------------------------------------------------
def _ts_to_dt(ts) -> str | None:
    """秒级时间戳转 `YYYY-MM-DD HH:MM:SS`。"""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, TypeError):
        return None


def _len_to_sec(length) -> int | None:
    """投稿时长 "MM:SS" / "HH:MM:SS" 或秒数转整数秒。"""
    if isinstance(length, int):
        return length if length > 0 else None
    if not isinstance(length, str) or ":" not in length:
        return None
    parts = length.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None
    return None


def _clean_text(text) -> str:
    """去特殊空白（制表符/换行/全角空格），保留普通文本。"""
    if not text:
        return ""
    return re.sub(r"[\t\r\n\u3000]+", " ", text).strip()


def _tname_of(tid) -> str | None:
    """从配置分区名单反查 tname（数据字典：不用接口返回名）。"""
    try:
        tid = int(tid)
    except (ValueError, TypeError):
        return None
    for name, t in PARTITIONS.items():
        if t == tid:
            return name
    return None


# ---------------------------------------------------------------------------
# 读原始 JSON
# ---------------------------------------------------------------------------
def _load_head_videos() -> list[dict]:
    """读榜单 ranking/*.json，返回 head 视频列表（含 rank_no、分区）。"""
    head: list[dict] = []
    for f in sorted((RAW_DIR / "ranking").glob("*.json")):
        tid = int(f.stem)
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for idx, it in enumerate(d.get("list") or []):
            owner = it.get("owner") or {}
            head.append({
                "bvid": it.get("bvid"), "aid": it.get("aid"), "cid": it.get("cid"),
                "title": it.get("title"), "descr": it.get("desc"),
                "pubdate": it.get("pubdate"), "duration": it.get("duration"),
                "tid": tid, "tname": _tname_of(tid),
                "owner_mid": owner.get("mid"), "owner_name": owner.get("name"),
                "rank_no": idx + 1,
            })
    return head


def _load_control_videos() -> list[dict]:
    """读投稿 upper_videos/*.json，返回 control 视频列表。"""
    control: list[dict] = []
    for f in sorted((RAW_DIR / "upper_videos").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        vlist = (d.get("list") or {}).get("vlist") or []
        for v in vlist:
            control.append({
                "bvid": v.get("bvid"), "aid": v.get("aid"), "cid": None,
                "title": v.get("title"), "descr": v.get("description"),
                "pubdate": v.get("created"), "duration": v.get("length"),
                "tid": v.get("typeid"), "tname": _tname_of(v.get("typeid") or 0),
                "owner_mid": v.get("mid"), "owner_name": v.get("author"),
            })
    return control


def _load_uppers() -> list[dict]:
    """读 UP主资料 upper/*.json。"""
    uppers: list[dict] = []
    for f in sorted((RAW_DIR / "upper").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("mid") is not None:
            uppers.append(d)
    return uppers


# ---------------------------------------------------------------------------
# 写库
# ---------------------------------------------------------------------------
_VIDEO_COLS = ("bvid, aid, cid, title, descr, pubdate, duration, tid, rid, tname, "
               "owner_mid, owner_name, sample_group, rank_no, is_recent_12m, first_seen_batch")


def _video_row(v: dict, sample_group: str, batch_id: str) -> tuple:
    """把视频 dict 转成 videos 表的一行参数。"""
    return (
        v.get("bvid"), v.get("aid"), v.get("cid"),
        _clean_text(v.get("title")), _clean_text(v.get("descr")),
        _ts_to_dt(v.get("pubdate")), _len_to_sec(v.get("duration")),
        v.get("tid"), None, v.get("tname"),
        v.get("owner_mid"), v.get("owner_name"),
        sample_group, v.get("rank_no"),
        1 if sample_group == "control" else None,
        batch_id,
    )


def _write_videos(head: list[dict], control: list[dict], batch_id: str) -> tuple[int, int, int]:
    """写 videos 表（head 优先），返回 (head 数, control 数, 剔除重复数)。"""
    conn = get_connection()
    head_n = control_n = dup = 0
    try:
        for v in head:
            conn.execute(f"INSERT OR REPLACE INTO videos ({_VIDEO_COLS}) "
                         f"VALUES ({', '.join('?' * 16)})",
                         _video_row(v, "head", batch_id))
            head_n += 1
        for v in control:
            if conn.execute("SELECT 1 FROM videos WHERE bvid=?", (v.get("bvid"),)).fetchone():
                dup += 1
                continue
            conn.execute(f"INSERT OR IGNORE INTO videos ({_VIDEO_COLS}) "
                         f"VALUES ({', '.join('?' * 16)})",
                         _video_row(v, "control", batch_id))
            control_n += 1
        conn.commit()
    finally:
        conn.close()
    return head_n, control_n, dup


def _write_uppers(uppers: list[dict]) -> int:
    """写 uppers 表（fans 缺失不填 0，防破圈度除零）。"""
    conn = get_connection()
    n = 0
    try:
        for u in uppers:
            fans = u.get("fans")
            if fans is None or fans <= 0:
                fans = None  # 缺失标记，不填 0
            conn.execute(
                "INSERT OR REPLACE INTO uppers (mid, name, fans, archive_count, collect_time) "
                "VALUES (?, ?, ?, ?, ?)",
                (u.get("mid"), u.get("name"), fans, u.get("archive_count"), now_str()),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def _clean_ugc_time() -> tuple[int, int]:
    """清洗弹幕/评论异常时间戳（早于视频发布或晚于当前时间），返回剔除条数。"""
    conn = get_connection()
    removed_d = removed_c = 0
    try:
        pubs = {r["bvid"]: r["pubdate"] for r in
                conn.execute("SELECT bvid, pubdate FROM videos WHERE pubdate IS NOT NULL")}
        for table, pk in [("danmaku", "dmid"), ("comments", "rpid")]:
            for bvid, pub in pubs.items():
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE bvid=? AND (ctime < ? OR ctime > ?)",
                    (bvid, pub, now_str()),
                )
                if table == "danmaku":
                    removed_d += cur.rowcount
                else:
                    removed_c += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return removed_d, removed_c


def _print_snapshot_overview() -> None:
    """打印快照概览（覆盖轮次、每视频快照数分布、相邻间隔分布），不写 snapshots。"""
    conn = get_connection()
    try:
        rounds = conn.execute("SELECT COUNT(DISTINCT collect_time) FROM snapshots").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        bvids = conn.execute("SELECT COUNT(DISTINCT bvid) FROM snapshots").fetchone()[0]
        times = [r[0] for r in conn.execute(
            "SELECT DISTINCT collect_time FROM snapshots ORDER BY collect_time")]
        log(f"[快照概览] 覆盖 {rounds} 轮 / {bvids} 视频 / 共 {total} 条")
        if len(times) >= 2:
            from datetime import datetime as dt
            gaps = [int((dt.fromisoformat(times[i + 1]) - dt.fromisoformat(times[i])).total_seconds())
                    for i in range(len(times) - 1)]
            log(f"[快照间隔] 相邻轮次间隔(秒)：{gaps}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run() -> int:
    """执行清洗入库全流程。"""
    batch_id = f"clean_{now_str().replace('-', '').replace(':', '').replace(' ', '')}"
    head = _load_head_videos()
    control = _load_control_videos()
    uppers = _load_uppers()

    log(f"[原始] head 榜单 {len(head)} 条 / control 对照 {len(control)} 条 / UP主 {len(uppers)} 个")

    head_n, control_n, dup = _write_videos(head, control, batch_id)
    upper_n = _write_uppers(uppers)
    removed_d, removed_c = _clean_ugc_time()

    log(f"[入库] videos：head {head_n} / control {control_n} / 剔除重复 {dup}")
    log(f"[入库] uppers：{upper_n} 个")
    log(f"[清洗] 异常时间戳剔除：弹幕 {removed_d} / 评论 {removed_c}")
    _print_snapshot_overview()
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    argparse.ArgumentParser(description="B站原始数据清洗入库").parse_args(argv)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
