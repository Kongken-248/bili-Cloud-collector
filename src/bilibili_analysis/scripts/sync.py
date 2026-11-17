"""云端与本地数据合并脚本。

拉取云端仓库里的快照 JSON（data/cloud/*.json）合并到本地 snapshots 表：
- 同主键（bvid + collect_time）保留更新时间晚者（INSERT OR REPLACE）；
- 弹幕/评论正文仅以本地为准，本脚本不触碰；
- 合并结果写 batch_log（来源 cloud），供采集管理页展示。

用法：
    python -m bilibili_analysis.scripts.sync [--no-pull]
"""

from __future__ import annotations

import argparse
import json
import subprocess

from bilibili_analysis.core.config import CLOUD_DIR, PROJECT_ROOT
from bilibili_analysis.core.db import get_connection
from bilibili_analysis.scripts._common import log, now_str


def _git_pull() -> bool:
    """在项目根目录执行 git pull（拉取云端快照数据），失败返回 False。"""
    try:
        result = subprocess.run(
            ["git", "pull", "--no-edit"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            return True
        log(f"[sync] git pull 失败：{result.stderr.strip()[:120]}")
        return False
    except Exception as e:
        log(f"[sync] git pull 异常：{e}")
        return False


def _merge_cloud() -> int:
    """读 data/cloud/*.json，合并到 snapshots 表，返回合并条数。"""
    conn = get_connection()
    merged = 0
    try:
        files = sorted(CLOUD_DIR.glob("snapshot_*.json")) if CLOUD_DIR.exists() else []
        for f in files:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            collect_time = d.get("collect_time", "")
            for item in d.get("items", []):
                bvid = item.get("bvid")
                if not bvid or not collect_time:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO snapshots "
                    "(bvid, collect_time, view, \"like\", coin, fav, share, reply, danmaku) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (bvid, collect_time,
                     item.get("view", 0), item.get("like", 0), item.get("coin", 0),
                     item.get("fav", 0), item.get("share", 0), item.get("reply", 0),
                     item.get("danmaku", 0)),
                )
                merged += 1
        conn.commit()
    finally:
        conn.close()
    return merged


def _log_batch(merged: int, pulled: bool) -> None:
    """写一条 batch_log（来源 cloud）。"""
    batch_id = f"cloud_sync_{now_str().replace('-', '').replace(':', '').replace(' ', '')}"
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO batch_log "
            "(batch_id, source, batch_type, count, start_time, end_time, status, fail_list) "
            "VALUES (?, 'cloud', '快照', ?, ?, ?, ?, '[]')",
            (batch_id, merged, now_str(), now_str(), "ok" if pulled else "no_pull"),
        )
        conn.commit()
    finally:
        conn.close()


def run(no_pull: bool) -> int:
    """执行拉取 + 合并。"""
    pulled = True if no_pull else _git_pull()
    merged = _merge_cloud()
    _log_batch(merged, pulled)
    log(f"[sync] 合并云端快照 {merged} 条（{'已 pull' if pulled else '跳过 pull'}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="云端快照与本地数据合并")
    parser.add_argument("--no-pull", action="store_true", help="跳过 git pull（仅合并本地已拉取的文件）")
    args = parser.parse_args(argv)
    return run(args.no_pull)


if __name__ == "__main__":
    raise SystemExit(main())
