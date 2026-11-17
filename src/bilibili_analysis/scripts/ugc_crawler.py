"""弹幕 / 评论本地采集器（登录态）。

对全部 head 视频（榜单视频，来源 data/raw/video/*.json 的详情落盘）：
- 弹幕：dm/web/view 拿声明数 + 分段配置，再按 cid 逐段拉 seg.so（protobuf 二进制），
  写 danmaku 表 + danmaku_fetch_log 对账（declared/got/ratio/seg_count）；
- 评论：按 aid 拉一级热评（主楼，sort=2）封顶 N，楼中楼仅保留 rcount 不采正文，
  写 comments 表 + comment_fetch_log 对账。

正文只落本地库（data/bilibili.db），不入云端仓库。

测试参数：--limit 限制视频数、--no-comment 跳过评论。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime

from bilibili_analysis.core.config import COMMENT_CAP_N, RAW_DIR
from bilibili_analysis.core.db import get_connection
from bilibili_analysis.scripts._common import http_get, log, make_session, now_str

_DM_VIEW_URL = "https://api.bilibili.com/x/v2/dm/web/view"
_DM_SEG_URL = "https://api.bilibili.com/x/v2/dm/web/seg.so"
_REPLY_URL = "https://api.bilibili.com/x/v2/reply"


# ---------------------------------------------------------------------------
# protobuf 轻量解析（仅弹幕接口，字段按 B站 公开 proto 定义）
# ---------------------------------------------------------------------------
def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    """读取一个 varint，返回 (值, 新位置)。"""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _dm_page_size(buf: bytes) -> int:
    """解析 dm/web/view，返回每段毫秒 page_size_ms（顶层 f4=DmSegConfig.f1）。"""
    page_size = 360000
    pos, n = 0, len(buf)
    while pos < n:
        tag, pos = _varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            _, pos = _varint(buf, pos)
        elif wire == 2:
            length, pos = _varint(buf, pos)
            if field == 4:
                # 嵌套 DmSegConfig：只取 f1（page_size_ms）
                p2, end = pos, pos + length
                while p2 < end:
                    t2, p2 = _varint(buf, p2)
                    f2, w2 = t2 >> 3, t2 & 7
                    if w2 == 0:
                        v2, p2 = _varint(buf, p2)
                        if f2 == 1:
                            page_size = v2
                    elif w2 == 2:
                        l2, p2 = _varint(buf, p2)
                        p2 += l2
                    elif w2 == 5:
                        p2 += 4
                    elif w2 == 1:
                        p2 += 8
            pos += length
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            break
    return page_size


def _dm_seg_elems(buf: bytes) -> list[dict]:
    """解析 seg.so，返回弹幕元素列表。顶层 f1=repeated DanmakuElem。"""
    elems: list[dict] = []
    pos, n = 0, len(buf)
    while pos < n:
        tag, pos = _varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 2:
            length, pos = _varint(buf, pos)
            if field == 1:
                elems.append(_parse_dm_elem(buf[pos:pos + length]))
            pos += length
        elif wire == 0:
            _, pos = _varint(buf, pos)
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            break
    return elems


def _parse_dm_elem(buf: bytes) -> dict:
    """解析单条 DanmakuElem（f1=id, f2=progress_ms, f3=mode, f4=fontsize,
    f5=color, f6=midHash, f7=content, f8=ctime）。"""
    e: dict = {}
    pos, n = 0, len(buf)
    while pos < n:
        tag, pos = _varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
            e[field] = value
        elif wire == 2:
            length, pos = _varint(buf, pos)
            e[field] = buf[pos:pos + length].decode("utf-8", errors="replace")
            pos += length
        elif wire == 5:
            pos += 4
        elif wire == 1:
            pos += 8
        else:
            break
    return e


def _hash_mid(mid: int | str) -> str:
    """评论 mid 匿名化（数据字典：不追踪个人，只做结构计算）。"""
    return hashlib.sha256(str(mid).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------
def _load_videos() -> list[dict]:
    """从 data/raw/video/*.json 读取已采集的视频详情（head 视频）。"""
    videos: list[dict] = []
    for f in sorted((RAW_DIR / "video").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("cid"):
                d.setdefault("bvid", f.stem)
                videos.append(d)
        except Exception:
            continue
    return videos


def fetch_danmaku(session, cid: int, duration: int) -> tuple[list[dict], int]:
    """拉取单个视频的全量可见弹幕（seg.so 分段），返回 (弹幕列表, 分段数)。

    注意：seg.so 只能采到「实时弹幕」，历史归档弹幕不在其中；因此对账时
    declared 取详情接口 stat.danmaku（历史累计总数），ratio 反映实时弹幕占比。
    """
    view = session.get(_DM_VIEW_URL, params={"type": 1, "oid": cid}, timeout=20)
    page_size = _dm_page_size(view.content)
    seg_count = max(1, -(-(duration * 1000) // page_size))  # ceil
    elems: list[dict] = []
    for idx in range(1, seg_count + 1):
        resp = session.get(_DM_SEG_URL, params={"type": 1, "oid": cid, "segment_index": idx}, timeout=20)
        if resp.status_code != 200:
            break
        elems.extend(_dm_seg_elems(resp.content))
    return elems, seg_count


def fetch_comments(session, aid: int, cap_n: int) -> tuple[list[dict], int, int, int]:
    """拉取一级热评（主楼），封顶 cap_n 条。

    返回 (一级评论列表, reported 接口报告总数, pages 翻页数, complete 是否完整)。
    complete=1 表示未触发封顶（采完全部）；0 表示触发 cap_n 截断。
    """
    replies: list[dict] = []
    reported, pages, complete = 0, 0, 0
    pn = 1
    while len(replies) < cap_n:
        data = http_get(session, _REPLY_URL, {"type": 1, "oid": aid, "pn": pn, "ps": 20, "sort": 2})
        if not data or data.get("code") != 0:
            break
        body = data.get("data") or {}
        reported = (body.get("page") or {}).get("count", 0)
        page_replies = body.get("replies") or []
        if not page_replies:
            complete = 1
            break
        replies.extend(page_replies)
        pages = pn
        pn += 1
    if len(replies) < cap_n:
        complete = 1
    return replies[:cap_n], reported, pages, complete


# ---------------------------------------------------------------------------
# 写库
# ---------------------------------------------------------------------------
def _ts(value: int) -> str:
    """秒级时间戳转 `YYYY-MM-DD HH:MM:SS`。"""
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _write_danmaku(bvid: str, elems: list[dict], declared: int, seg_count: int) -> int:
    """写 danmaku 表 + danmaku_fetch_log 对账，返回实采条数。"""
    conn = get_connection()
    got = 0
    try:
        for e in elems:
            content = (e.get(7) or "").strip()
            if not content:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO danmaku "
                "(dmid, bvid, progress, ctime, mode, fontsize, color, mid_hash, content) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (e.get(1, 0), bvid, (e.get(2, 0) or 0) // 1000, _ts(e.get(8, 0)),
                 e.get(3, 0), e.get(4, 0), e.get(5, 0), e.get(6, ""), content),
            )
            got += 1
        ratio = round(got / declared, 4) if declared else None
        conn.execute(
            "INSERT OR REPLACE INTO danmaku_fetch_log "
            "(bvid, fetch_time, declared, got, ratio, seg_count) VALUES (?, ?, ?, ?, ?, ?)",
            (bvid, now_str(), declared, got, ratio, seg_count),
        )
        conn.commit()
    finally:
        conn.close()
    return got


def _write_comments(bvid: str, replies: list[dict], reported: int, pages: int,
                    complete: int, cap_n: int) -> int:
    """写 comments 表（仅一级评论正文）+ comment_fetch_log 对账，返回实采条数。"""
    conn = get_connection()
    got = 0
    try:
        for r in replies:
            message = ((r.get("content") or {}).get("message") or "").strip()
            if not message:
                continue
            mid = (r.get("member") or {}).get("mid", "")
            conn.execute(
                "INSERT OR IGNORE INTO comments "
                "(rpid, bvid, ctime, \"like\", rcount, mid_hash, content, sentiment) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (r.get("rpid"), bvid, _ts(r.get("ctime", 0)), r.get("like", 0),
                 r.get("rcount", 0), _hash_mid(mid), message),
            )
            got += 1
        conn.execute(
            "INSERT OR REPLACE INTO comment_fetch_log "
            "(bvid, fetch_time, reported, got, pages, complete, cap_n) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bvid, now_str(), reported, got, pages, complete, cap_n),
        )
        conn.commit()
    finally:
        conn.close()
    return got


def run(limit: int | None, no_comment: bool) -> int:
    """对全部 head 视频执行弹幕 + 评论采集。"""
    session = make_session(with_sessdata=True)
    videos = _load_videos()
    if limit is not None:
        videos = videos[:limit]
    log(f"待采集视频：{len(videos)} 个")
    for v in videos:
        bvid, cid, aid = v.get("bvid"), v.get("cid"), v.get("aid")
        duration = v.get("duration") or 0
        if not cid or not aid or not duration:
            log(f"[跳过] {bvid}：缺 cid/aid/duration")
            continue
        declared = (v.get("stat") or {}).get("danmaku", 0)  # 详情接口声明总弹幕数
        elems, seg_count = fetch_danmaku(session, cid, duration)
        got = _write_danmaku(bvid, elems, declared, seg_count)
        log(f"[弹幕] {bvid}：declared {declared} / got {got} / 段 {seg_count}")
        if not no_comment:
            replies, reported, pages, complete = fetch_comments(session, aid, COMMENT_CAP_N)
            cgot = _write_comments(bvid, replies, reported, pages, complete, COMMENT_CAP_N)
            log(f"[评论] {bvid}：reported {reported} / got {cgot} / 完整 {complete}")
    log("[完成] 弹幕/评论采集结束")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="B站弹幕 / 评论本地采集（登录态）")
    parser.add_argument("--limit", type=int, default=None, help="限制采集视频数（小样本验证用）")
    parser.add_argument("--no-comment", action="store_true", help="跳过评论采集")
    args = parser.parse_args(argv)
    return run(args.limit, args.no_comment)


if __name__ == "__main__":
    raise SystemExit(main())
