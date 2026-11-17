"""快照采集脚本。

对全部 bvid（head 榜单视频 + control 对照投稿）重采统计字段写 snapshots 表，
首轮即写 T0，后续轮次写 T1、T2……（Δ 与窗口增量据此计算）。

只调公开详情接口（view），无需登录态；云端定时（GitHub Actions + cron-job.org）
也复用同一入口，故本脚本不得依赖 SESSDATA。

快照合法用途（数据字典 B 级）：当前时点横截面、相邻时点 Δ、窗口内累计增量；
禁止画「发布后天数 × 播放量」曲线或做增长建模。

用法：
    python -m bilibili_analysis.scripts.snapshot [--limit N] [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json

from bilibili_analysis.core.config import CLOUD_DIR, RAW_DIR
from bilibili_analysis.core.db import get_connection
from bilibili_analysis.scripts._common import http_get, log, make_session, now_str

_VIDEO_URL = "https://api.bilibili.com/x/web-interface/view"

# 快照字段（对齐数据字典 snapshots 表，`like` 为 SQLite 关键字需加引号）
_SNAP_COLS = ["view", "like", "coin", "fav", "share", "reply", "danmaku"]


def _collect_bvids() -> list[str]:
    """收集快照对象 bvid，按优先级：
    1. data/cloud/bvids.json（本地生成的云端种子清单）；
    2. data/cloud/snapshot_*.json（云端已有快照）；
    3. videos 表（本地，clean.py 已入库）；
    4. raw 落盘（本地首轮，clean 之前）。
    """
    bvids: set[str] = set()
    seed = CLOUD_DIR / "bvids.json"
    if seed.exists():
        try:
            bvids.update(json.loads(seed.read_text(encoding="utf-8")).get("bvids", []))
        except Exception:
            pass
    if CLOUD_DIR.exists():
        for f in CLOUD_DIR.glob("snapshot_*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                bvids.update(i.get("bvid") for i in d.get("items", []) if i.get("bvid"))
            except Exception:
                continue
    if not bvids:
        conn = get_connection()
        try:
            bvids.update(r["bvid"] for r in conn.execute("SELECT bvid FROM videos"))
        finally:
            conn.close()
    if not bvids:
        video_dir = RAW_DIR / "video"
        if video_dir.exists():
            bvids.update(f.stem for f in video_dir.glob("*.json"))
        uv_dir = RAW_DIR / "upper_videos"
        if uv_dir.exists():
            for f in uv_dir.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    vlist = (d.get("list") or {}).get("vlist") or []
                    bvids.update(v.get("bvid") for v in vlist if v.get("bvid"))
                except Exception:
                    continue
    return sorted(bvids)


def _save_bvid_seed(bvids: list[str]) -> None:
    """落盘 bvid 清单到 data/cloud/bvids.json（云端快照的种子来源）。"""
    CLOUD_DIR.mkdir(parents=True, exist_ok=True)
    (CLOUD_DIR / "bvids.json").write_text(
        json.dumps({"bvids": bvids}, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def fetch_stat(session, bvid: str) -> dict | None:
    """调详情接口拿当前统计字段（view/like/coin/fav/share/reply/danmaku）。"""
    data = http_get(session, _VIDEO_URL, {"bvid": bvid})
    if data and data.get("code") == 0:
        return (data.get("data") or {}).get("stat") or {}
    return None


def _write_snapshot(bvid: str, collect_time: str, stat: dict) -> None:
    """写一条快照（复合主键 bvid+collect_time，重复执行覆盖，幂等）。"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots "
            "(bvid, collect_time, view, \"like\", coin, fav, share, reply, danmaku) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bvid, collect_time,
             stat.get("view", 0), stat.get("like", 0), stat.get("coin", 0),
             stat.get("fav", 0), stat.get("share", 0), stat.get("reply", 0),
             stat.get("danmaku", 0)),
        )
        conn.commit()
    finally:
        conn.close()


def _save_cloud_round(collect_time: str, items: list[dict]) -> None:
    """落盘当轮快照到 data/cloud/（供云端 git push、本地 sync 合并）。"""
    ts = collect_time.replace("-", "").replace(":", "").replace(" ", "_")
    CLOUD_DIR.mkdir(parents=True, exist_ok=True)
    path = CLOUD_DIR / f"snapshot_{ts}.json"
    path.write_text(
        json.dumps({"collect_time": collect_time, "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(limit: int | None, date: str | None) -> int:
    """执行快照采集。"""
    session = make_session()  # 公开接口，无需登录态
    bvids = _collect_bvids()
    _save_bvid_seed(bvids)  # 落盘完整 bvid 清单（云端快照种子，先于 limit 截断）
    if limit is not None:
        bvids = bvids[:limit]
    collect_time = f"{date} 00:00:00" if date else now_str()
    ok = 0
    round_items: list[dict] = []
    for bvid in bvids:
        stat = fetch_stat(session, bvid)
        if stat is None:
            log(f"[快照失败] {bvid}")
            continue
        _write_snapshot(bvid, collect_time, stat)
        item = {"bvid": bvid}
        item.update({k: stat.get(k, 0) for k in _SNAP_COLS})
        round_items.append(item)
        ok += 1
    _save_cloud_round(collect_time, round_items)
    log(f"[完成] 快照 {ok}/{len(bvids)} 条 @ {collect_time}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="B站视频统计字段快照采集")
    parser.add_argument("--limit", type=int, default=None, help="限制快照视频数（测试用）")
    parser.add_argument("--date", type=str, default=None, help="指定快照日期（YYYY-MM-DD，测试幂等用）")
    args = parser.parse_args(argv)
    return run(args.limit, args.date)


if __name__ == "__main__":
    raise SystemExit(main())
