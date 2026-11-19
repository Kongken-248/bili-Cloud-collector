"""快照采集脚本。

对全部 bvid（head 榜单视频 + control 对照投稿）重采统计字段写 snapshots 表，
首轮即写 T0，后续轮次写 T1、T2……（Δ 与窗口增量据此计算）。

只调公开详情接口（view），无需登录态；云端定时（GitHub Actions + cron-job.org）
也复用同一入口，故本脚本不得依赖 SESSDATA。

快照合法用途（数据字典 B 级）：当前时点横截面、相邻时点 Δ、窗口内累计增量；
禁止画「发布后天数 × 播放量」曲线或做增长建模。

用法：
    python -m scripts.snapshot [--limit N] [--date YYYY-MM-DD] [--retry-failed]

失败处理：
    - 可重试错误（超时 / -412 风控 / 5xx）由公共层按 3s→15s→60s 指数退避重试；
    - 永久错误（62012 稿件不存在等）不重试，直接记失败；
    - 当轮失败清单落盘 data/cloud/fail_log.json（bvid / 错误码 / 时间），
      下一轮可用 --retry-failed 只重采失败清单。
"""

from __future__ import annotations

import argparse
import json
import sqlite3

from core.config import CLOUD_DIR, DB_PATH, RAW_DIR
from scripts._common import http_get, log, make_session, now_str

_VIDEO_URL = "https://api.bilibili.com/x/web-interface/view"

# 快照字段（对齐数据字典 snapshots 表，`like` 为 SQLite 关键字需加引号）
_SNAP_COLS = ["view", "like", "coin", "fav", "share", "reply", "danmaku"]

# 失败清单固定路径（每轮覆盖，记录当轮失败明细）
_FAIL_LOG = CLOUD_DIR / "fail_log.json"

# 常见错误码的可读描述（fail_log 与汇总打印用）
_ERR_DESC = {
    62012: "稿件不可见（已删除/UP主隐藏）",
    -404: "稿件不可见（啥都木有）",
    -403: "访问权限不足",
    -412: "请求被拦截（风控）",
    62002: "稿件不可见（审核中/被锁定）",
    "network": "网络超时/连接失败（重试后仍失败）",
}


def _connect() -> sqlite3.Connection:
    """SQLite 直连（不依赖 db.py，避免云端引入 pandas 依赖）。

    云端数据库可能是新建的空库，连接时确保 snapshots 表存在（幂等）。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS snapshots ("
        "bvid TEXT, collect_time DATETIME, view INTEGER, \"like\" INTEGER, coin INTEGER, "
        "fav INTEGER, share INTEGER, reply INTEGER, danmaku INTEGER, "
        "PRIMARY KEY (bvid, collect_time))"
    )
    conn.commit()
    return conn


def _collect_bvids() -> list[str]:
    """收集快照对象 bvid（**仅 head**，本地与云端口径统一）。

    来源优先级：data/cloud/bvids.json 种子 → 已有快照 → videos 表 head → raw 兜底。
    control 不做快照（数据字典）：其截面数据由 videos.view_t0（首次观测时点基准播放量）承担。
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
    conn = _connect()
    try:
        # 统一过滤：仅保留 head（数据字典 snapshots 仅 head；种子/历史快照 JSON
        # 可能含早期口径遗留的 control，一律与 videos.head 取交集剔除）
        head_set = {r["bvid"] for r in conn.execute(
            "SELECT bvid FROM videos WHERE sample_group='head'")}
        bvids &= head_set
    except sqlite3.OperationalError:
        pass  # 云端空库：信任种子（种子本身即 head 清单）
    finally:
        conn.close()
    if not bvids:
        video_dir = RAW_DIR / "video"
        if video_dir.exists():
            bvids.update(f.stem for f in video_dir.glob("*.json"))
    return sorted(bvids)


def _save_bvid_seed(bvids: list[str]) -> None:
    """落盘 bvid 清单到 data/cloud/bvids.json（云端快照的种子来源）。"""
    CLOUD_DIR.mkdir(parents=True, exist_ok=True)
    (CLOUD_DIR / "bvids.json").write_text(
        json.dumps({"bvids": bvids}, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def fetch_stat(session, bvid: str) -> tuple[dict | None, int | str | None]:
    """调详情接口拿当前统计字段。

    返回 (stat, err)：
    - 成功：(stat_dict, None)；
    - 失败：(None, err)，err 为接口业务错误码（如 62012）或
      "network"（公共层退避重试耗尽仍连不上）。
    永久错误码不重试（公共层直接透传），可重试错误已在其内部退避重试。
    """
    data = http_get(session, _VIDEO_URL, {"bvid": bvid}, timeout=10)
    if data is None:
        return None, "network"
    code = data.get("code")
    if code == 0:
        return (data.get("data") or {}).get("stat") or {}, None
    return None, code


def _write_snapshot(bvid: str, collect_time: str, stat: dict) -> None:
    """写一条快照（复合主键 bvid+collect_time，重复执行覆盖，幂等）。"""
    conn = _connect()
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


def _save_fail_log(collect_time: str, total: int, ok: int,
                   failures: list[dict]) -> None:
    """落盘当轮失败清单到 data/cloud/fail_log.json（每轮覆盖）。

    供人工排查与 --retry-failed 下一轮定向重采；无失败也覆盖写空清单，
    避免上一轮的旧失败清单被误当作当前状态。
    """
    CLOUD_DIR.mkdir(parents=True, exist_ok=True)
    _FAIL_LOG.write_text(
        json.dumps({
            "collect_time": collect_time,
            "total": total,
            "ok": ok,
            "fail_count": len(failures),
            "failures": failures,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_failed_bvids() -> list[str]:
    """读上一轮 fail_log.json 的失败 bvid 清单（--retry-failed 用）。"""
    if not _FAIL_LOG.exists():
        log("[retry-failed] 未找到 fail_log.json，无失败清单可重采")
        return []
    try:
        d = json.loads(_FAIL_LOG.read_text(encoding="utf-8"))
    except Exception:
        log("[retry-failed] fail_log.json 解析失败，放弃重采")
        return []
    bvids = [f.get("bvid") for f in d.get("failures", []) if f.get("bvid")]
    log(f"[retry-failed] 上轮失败清单 {len(bvids)} 条，开始定向重采")
    return sorted(set(bvids))


def run(limit: int | None, date: str | None, retry_failed: bool = False) -> int:
    """执行快照采集（仅 head，本地与云端口径统一）。"""
    session = make_session()  # 公开接口，无需登录态
    if retry_failed:
        bvids = _load_failed_bvids()
    else:
        bvids = _collect_bvids()
        _save_bvid_seed(bvids)  # 落盘 bvid 清单（先于 limit 截断）
    if limit is not None:
        bvids = bvids[:limit]
    collect_time = f"{date} 00:00:00" if date else now_str()
    ok = 0
    round_items: list[dict] = []
    failures: list[dict] = []
    for bvid in bvids:
        stat, err = fetch_stat(session, bvid)
        if err is not None:
            desc = _ERR_DESC.get(err, "未知错误")
            failures.append({"bvid": bvid, "code": err, "error": desc,
                             "time": now_str()})
            log(f"[快照失败] {bvid} code={err} {desc}")
            continue
        _write_snapshot(bvid, collect_time, stat)
        item = {"bvid": bvid}
        item.update({k: stat.get(k, 0) for k in _SNAP_COLS})
        round_items.append(item)
        ok += 1
    _save_cloud_round(collect_time, round_items)
    _save_fail_log(collect_time, len(bvids), ok, failures)
    log(f"[完成] 快照 {ok}/{len(bvids)} 条 @ {collect_time}")
    if failures:
        by_code: dict = {}
        for f in failures:
            by_code.setdefault(f["code"], []).append(f["bvid"])
        for c, v in sorted(by_code.items(), key=lambda x: str(x[0])):
            log(f"[失败汇总] code={c} {_ERR_DESC.get(c, '未知错误')} "
                f"×{len(v)}: {', '.join(v)}")
    else:
        log("[失败汇总] 0 条，全部成功")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="B站 head 视频统计字段快照采集")
    parser.add_argument("--limit", type=int, default=None, help="限制快照视频数（测试用）")
    parser.add_argument("--date", type=str, default=None, help="指定快照日期（YYYY-MM-DD，测试幂等用）")
    parser.add_argument("--retry-failed", action="store_true",
                        help="只重采上一轮 fail_log.json 中的失败清单")
    args = parser.parse_args(argv)
    return run(args.limit, args.date, args.retry_failed)


if __name__ == "__main__":
    raise SystemExit(main())
