"""榜单 / UP主 / 对照投稿采集器。

按模块一口径执行：榜单采集（head）→ 冻结自检 → UP主回查（空间资料
+ 近期投稿，双截断）→ 对照投稿（control）。仅落盘原始 JSON 与 batch_log，
主表（videos / uppers）由模块二 clean.py 写入；snapshots 由 snapshot.py 写。

测试参数：--limit 限制条数、--partition 指定单个分区（便于小样本验证）。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from bilibili_analysis.core.config import (
    PARTITIONS,
    RAW_DIR,
    UP_DEGRADE_RISK_LIMIT,
    UP_DEGRADE_TIME_LIMIT,
)
from bilibili_analysis.core.db import get_connection
from bilibili_analysis.scripts._common import (
    http_get,
    log,
    make_session,
    now_str,
    save_raw,
)

# 接口地址（实测确认：排行榜 rid 传新版分区 tid，返回实时数据）
_RANKING_URL = "https://api.bilibili.com/x/web-interface/ranking/v2"
_VIDEO_URL = "https://api.bilibili.com/x/web-interface/view"
_UPPER_URL = "https://api.bilibili.com/x/space/acc/info"
_UPPER_STAT_URL = "https://api.bilibili.com/x/relation/stat"
_UPPER_VIDEOS_URL = "https://api.bilibili.com/x/space/wbi/arc/search"

# 对照投稿双截断（模块一已确认口径）
_CONTROL_MAX_PER_UPPER = 30
_CONTROL_RECENT_DAYS = 365

# 冻结自检阈值（对齐提示词 4.3：近 7 天投稿占比 <20%，或相邻两轮重合率 >90%）
_FREEZE_RECENT_DAYS = 7
_FREEZE_RECENT_RATIO = 0.2   # 近 7 天投稿占比低于此值视为疑似冻结
_FREEZE_DIFF_RATIO = 0.9     # 与上轮榜单重合率高于此值视为无变化

_STATE_FILE = RAW_DIR / "crawl_state.json"


def _load_state() -> dict:
    """读取断点续采状态（已完成分区 / UP主）。"""
    if _STATE_FILE.exists():
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    return {"partitions_done": [], "uppers_done": []}


def _save_state(state: dict) -> None:
    """写回断点续采状态。"""
    _STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_ranking(session, tid: int, limit: int | None = None) -> list[dict]:
    """采集单个分区的榜单，返回视频条目列表（head），并落盘原始数据。"""
    data = http_get(session, _RANKING_URL, {"rid": tid, "type": "all"})
    if not data or not isinstance(data.get("data"), dict):
        return []
    items = data["data"].get("list") or []
    if limit is not None:
        items = items[:limit]
    save_raw(f"ranking/{tid}.json", data["data"])
    return items


def check_freeze(items: list[dict], prev_bvids: set[str]) -> tuple[bool, str]:
    """冻结自检，返回 (是否冻结, 原因)。

    两个信号分别防什么：
    - 近期投稿占比：防榜单停更（pubdate 整体陈旧）；
    - 与上轮重合率：防榜单长期不刷新（无新增头部）。
    """
    now_ts = time.time()
    recent = sum(
        1 for it in items
        if now_ts - int(it.get("pubdate", 0)) <= _FREEZE_RECENT_DAYS * 86400
    )
    if items:
        recent_ratio = recent / len(items)
        if recent_ratio < _FREEZE_RECENT_RATIO:
            return True, f"近期投稿占比 {recent_ratio:.1%} 低于阈值 {_FREEZE_RECENT_RATIO:.0%}"
    cur_bvids = {it.get("bvid") for it in items if it.get("bvid")}
    if prev_bvids and cur_bvids:
        overlap = len(cur_bvids & prev_bvids) / len(cur_bvids)
        if overlap > _FREEZE_DIFF_RATIO:
            return True, f"与上轮榜单重合率 {overlap:.1%} 高于阈值 {_FREEZE_DIFF_RATIO:.0%}"
    return False, ""


def fetch_video_detail(session, bvid: str) -> dict | None:
    """补全视频详情（aid / cid / 完整 stat），落盘原始 JSON。"""
    data = http_get(session, _VIDEO_URL, {"bvid": bvid})
    if data and data.get("code") == 0:
        save_raw(f"video/{bvid}.json", data["data"])
        return data["data"]
    return None


def fetch_upper_info(session, mid: int) -> dict | None:
    """回查 UP主资料（name + fans），返回合并结构，由 run 统一落盘。

    acc/info 接口不含粉丝数字段，粉丝数需另调 relation/stat（follower）。
    """
    info = http_get(session, _UPPER_URL, {"mid": mid})
    stat = http_get(session, _UPPER_STAT_URL, {"vmid": mid})
    name = (info.get("data") or {}).get("name") if info else None
    fans = (stat.get("data") or {}).get("follower") if stat else None
    if name is None and fans is None:
        return None
    return {"mid": mid, "name": name, "fans": fans, "info": info, "stat": stat}


def fetch_upper_videos(session, mid: int, limit: int | None = None) -> tuple[list[dict], int]:
    """回查 UP主近期投稿（wbi 签名），做双截断：每 UP主 ≤30 条且仅近 12 个月。

    返回 (对照投稿列表 kept, 投稿总数 archive_count)；投稿总数取自接口
    page.count，供 uppers 表 archive_count 使用。
    """
    cutoff = time.time() - _CONTROL_RECENT_DAYS * 86400
    params = {"mid": mid, "ps": 30, "pn": 1, "order": "pubdate"}
    data = http_get(session, _UPPER_VIDEOS_URL, params, wbi=True)
    if not data or not isinstance(data.get("data"), dict):
        return [], 0
    archive_count = (data["data"].get("page") or {}).get("count", 0)
    vlist = data["data"].get("list", {}).get("vlist") or []
    kept = [v for v in vlist if int(v.get("created", 0)) >= cutoff]
    if limit is not None:
        kept = kept[:limit]
    else:
        kept = kept[:_CONTROL_MAX_PER_UPPER]
    save_raw(f"upper_videos/{mid}.json", data["data"])
    return kept, archive_count


def _log_batch(batch_type: str, count: int, start: str, status: str, failed: list[str]) -> None:
    """写一条 batch_log 记录（来源 local）。"""
    batch_id = f"local_{batch_type}_{start.replace('-', '').replace(':', '').replace(' ', '')}"
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO batch_log "
            "(batch_id, source, batch_type, count, start_time, end_time, status, fail_list) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (batch_id, "local", batch_type, count, start, now_str(), status,
             json.dumps(failed, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def run(limit: int | None, partition: str | None) -> int:
    """执行榜单 → 冻结自检 → UP主回查 → 对照投稿 全链路。

    注意：UP主投稿回查（wbi 接口）在当前环境需登录态，故全程带 SESSDATA；
    榜单/详情/资料等公开接口带登录态也无副作用。
    """
    session = make_session(with_sessdata=True)
    state = _load_state()
    failed: list[str] = []
    start = now_str()

    # 选定分区（默认全部六区，尊重断点）
    if partition:
        tids = {partition: PARTITIONS[partition]}
    else:
        tids = {k: v for k, v in PARTITIONS.items() if k not in state["partitions_done"]}

    head_items: list[dict] = []
    prev_bvids: set[str] = set()
    for name, tid in tids.items():
        items = fetch_ranking(session, tid, limit)
        frozen, reason = check_freeze(items, prev_bvids)
        if frozen:
            log(f"[告警] 分区 {name} 榜单疑似冻结：{reason}，停止后续采集")
            _log_batch("榜单", len(head_items), start, "frozen", failed)
            return 2
        prev_bvids = {it.get("bvid") for it in items if it.get("bvid")}
        head_items.extend(items)
        state["partitions_done"].append(name)
        _save_state(state)
        log(f"[榜单] {name}：{len(items)} 条")

    # 详情补全 aid/cid
    for it in head_items:
        bvid = it.get("bvid")
        if not bvid:
            continue
        if fetch_video_detail(session, bvid) is None:
            failed.append(bvid)

    # UP主回查：去重 owner_mid，带降级开关（连续风控失败达阈值触发抽样降级）
    mids = sorted({it.get("owner", {}).get("mid") for it in head_items
                   if it.get("owner", {}).get("mid")})
    risk_fail = 0
    degraded = False
    started = time.time()
    control_count = 0
    for mid in mids:
        if str(mid) in state["uppers_done"]:
            continue
        # 降级触发：预计剩余时长超限，或连续风控失败达阈值
        if not degraded and (
            (time.time() - started > UP_DEGRADE_TIME_LIMIT) or risk_fail >= UP_DEGRADE_RISK_LIMIT
        ):
            degraded = True
            log(f"[降级] UP主投稿回查降级为抽样：已耗时 {time.time() - started:.0f}s / 风控失败 {risk_fail} 次")
        info = fetch_upper_info(session, mid)
        if info is None:
            risk_fail += 1
            failed.append(f"upper:{mid}")
            continue
        vids, archive_count = fetch_upper_videos(session, mid, limit)
        info["archive_count"] = archive_count
        save_raw(f"upper/{mid}.json", info)
        control_count += len(vids)
        state["uppers_done"].append(str(mid))
        _save_state(state)
        log(f"[UP主] mid={mid}：资料 + 对照投稿 {len(vids)} 条{'（抽样）' if degraded else ''}")

    _log_batch("榜单/UP主", len(head_items) + control_count, start, "ok", failed)
    log(f"[完成] 榜单 {len(head_items)} 条，对照投稿 {control_count} 条，失败 {len(failed)} 项")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="榜单 / UP主 / 对照投稿采集器")
    parser.add_argument("--limit", type=int, default=None, help="限制每层采集条数（小样本验证用）")
    parser.add_argument("--partition", type=str, default=None, choices=list(PARTITIONS),
                        help="只采指定分区名")
    args = parser.parse_args(argv)
    return run(args.limit, args.partition)


if __name__ == "__main__":
    raise SystemExit(main())
