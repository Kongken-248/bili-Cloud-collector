"""SQLite 数据访问层：建表（幂等）+ 数据查询函数。

字段口径唯一真源：docs/数据字典.md。表结构不得在此处擅自修改。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from bilibili_analysis.core import config

# 建表 SQL（字段对齐数据字典；`like` 是 SQLite 关键字，作列名需双引号包裹）
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    bvid             TEXT PRIMARY KEY,
    aid              INTEGER,
    cid              INTEGER,
    title            TEXT,
    descr            TEXT,
    pubdate          DATETIME,
    duration         INTEGER,
    tid              INTEGER,
    rid              INTEGER,
    tname            TEXT,
    owner_mid        INTEGER,
    owner_name       TEXT,
    sample_group     TEXT,
    rank_no          INTEGER,
    is_recent_12m    INTEGER,
    first_seen_batch TEXT
);

CREATE TABLE IF NOT EXISTS uppers (
    mid           INTEGER PRIMARY KEY,
    name          TEXT,
    fans          INTEGER,
    archive_count INTEGER,
    collect_time  DATETIME
);

CREATE TABLE IF NOT EXISTS snapshots (
    bvid         TEXT,
    collect_time DATETIME,
    view         INTEGER,
    "like"       INTEGER,
    coin         INTEGER,
    fav          INTEGER,
    share        INTEGER,
    reply        INTEGER,
    danmaku      INTEGER,
    PRIMARY KEY (bvid, collect_time)
);

CREATE TABLE IF NOT EXISTS danmaku (
    dmid     INTEGER PRIMARY KEY,
    bvid     TEXT,
    progress INTEGER,
    ctime    DATETIME,
    mode     INTEGER,
    fontsize INTEGER,
    color    TEXT,
    mid_hash TEXT,
    content  TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    rpid      INTEGER PRIMARY KEY,
    bvid      TEXT,
    ctime     DATETIME,
    "like"    INTEGER,
    rcount    INTEGER,
    mid_hash  TEXT,
    content   TEXT,
    sentiment TEXT
);

CREATE TABLE IF NOT EXISTS danmaku_fetch_log (
    bvid       TEXT,
    fetch_time DATETIME,
    declared   INTEGER,
    got        INTEGER,
    ratio      REAL,
    seg_count  INTEGER,
    PRIMARY KEY (bvid, fetch_time)
);

CREATE TABLE IF NOT EXISTS comment_fetch_log (
    bvid       TEXT,
    fetch_time DATETIME,
    reported   INTEGER,
    got        INTEGER,
    pages      INTEGER,
    complete   INTEGER,
    cap_n      INTEGER,
    PRIMARY KEY (bvid, fetch_time)
);

CREATE TABLE IF NOT EXISTS batch_log (
    batch_id   TEXT PRIMARY KEY,
    source     TEXT,
    batch_type TEXT,
    count      INTEGER,
    start_time DATETIME,
    end_time   DATETIME,
    status     TEXT,
    fail_list  TEXT
);
"""

# 索引定义（对齐数据字典第 4 节）
_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_videos_sample_group ON videos(sample_group);",
    "CREATE INDEX IF NOT EXISTS idx_videos_owner_mid ON videos(owner_mid);",
    "CREATE INDEX IF NOT EXISTS idx_videos_tname ON videos(tname);",
    "CREATE INDEX IF NOT EXISTS idx_danmaku_bvid ON danmaku(bvid);",
    "CREATE INDEX IF NOT EXISTS idx_comments_bvid ON comments(bvid);",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_collect_time ON snapshots(collect_time);",
]


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """返回一个 SQLite 连接（可作为上下文管理器使用）。

    参数：
        db_path：数据库文件路径；缺省使用 config.DB_PATH。
    """
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | None = None) -> None:
    """幂等建表：创建全部八张表与索引，重复执行不报错、不产生重复结构。

    参数：
        db_path：数据库文件路径；缺省使用 config.DB_PATH。
    """
    with get_connection(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        for sql in _INDEX_SQL:
            conn.execute(sql)
        conn.commit()


def list_tables(db_path: Path | None = None) -> list[str]:
    """返回当前数据库中的表名列表（供验收与自检用）。"""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    return sorted(row["name"] for row in rows)


# ---------------------------------------------------------------------------
# 数据访问层（模块二）：全部带类型提示与中文 docstring，入参可哈希以兼容 st.cache_data
# ---------------------------------------------------------------------------
def get_videos(sample_group: str | None = None, tname: str | None = None,
               owner_mid: int | None = None, keyword: str | None = None,
               min_view: int | None = None, max_view: int | None = None) -> pd.DataFrame:
    """视频筛选：分区 / 样本层 / 关键词 / 播放区间（播放量取最新快照）。"""
    sql = """
        SELECT v.*, s.view AS latest_view
        FROM videos v
        LEFT JOIN snapshots s ON s.bvid = v.bvid AND s.collect_time = (
            SELECT MAX(collect_time) FROM snapshots WHERE bvid = v.bvid
        )
        WHERE 1=1
    """
    params: list = []
    if sample_group:
        sql += " AND v.sample_group = ?"
        params.append(sample_group)
    if tname:
        sql += " AND v.tname = ?"
        params.append(tname)
    if owner_mid is not None:
        sql += " AND v.owner_mid = ?"
        params.append(owner_mid)
    if keyword:
        sql += " AND v.title LIKE ?"
        params.append(f"%{keyword}%")
    if min_view is not None:
        sql += " AND s.view >= ?"
        params.append(min_view)
    if max_view is not None:
        sql += " AND s.view <= ?"
        params.append(max_view)
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_uppers() -> pd.DataFrame:
    """UP主资料（当前快照）。"""
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM uppers", conn)


def get_danmaku(bvid: str | None = None) -> pd.DataFrame:
    """弹幕查询（正文仅本地）。"""
    if bvid:
        with get_connection() as conn:
            return pd.read_sql_query("SELECT * FROM danmaku WHERE bvid=?", conn, params=(bvid,))
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM danmaku", conn)


def get_comments(bvid: str | None = None, limit: int | None = None) -> pd.DataFrame:
    """评论查询（仅一级热评，正文仅本地）。"""
    sql = "SELECT * FROM comments"
    params: list = []
    if bvid:
        sql += " WHERE bvid = ?"
        params.append(bvid)
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_snapshots(bvid: str | None = None) -> pd.DataFrame:
    """快照查询（B 级累计快照）。"""
    if bvid:
        with get_connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM snapshots WHERE bvid=? ORDER BY collect_time", conn, params=(bvid,))
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM snapshots ORDER BY bvid, collect_time", conn)


def get_delta_table() -> pd.DataFrame:
    """Δ 宽表：各指标 Δ + 增量率（分母 0 置 NULL）+ 实际间隔 + view(t)−view(T0)。

    只输出相邻时点的 Δ 与窗口累计增量（横轴=观测轮次），
    不输出「发布后天数 × 播放量」曲线，不做增长建模。
    """
    metrics = ["view", "like", "coin", "fav", "share", "reply", "danmaku"]
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT * FROM snapshots ORDER BY bvid, collect_time", conn)
    if df.empty:
        return df
    df["collect_time"] = pd.to_datetime(df["collect_time"])
    rows: list[dict] = []
    for bvid, g in df.groupby("bvid"):
        g = g.sort_values("collect_time")
        t0 = g.iloc[0]
        for i in range(1, len(g)):
            cur, prev = g.iloc[i], g.iloc[i - 1]
            row: dict = {
                "bvid": bvid,
                "collect_time": cur["collect_time"],
                "interval_sec": int((cur["collect_time"] - prev["collect_time"]).total_seconds()),
            }
            for m in metrics:
                row[f"{m}_delta"] = int(cur[m]) - int(prev[m])
                base = int(prev[m])
                row[f"{m}_rate"] = round((int(cur[m]) - base) / base, 6) if base else None
            row["view_cum"] = int(cur["view"]) - int(t0["view"])
            rows.append(row)
    return pd.DataFrame(rows)


def get_danmaku_ratio() -> pd.DataFrame:
    """弹幕对账表（declared/got/ratio，供 ratio 阈值剔除）。"""
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM danmaku_fetch_log ORDER BY fetch_time", conn)


def get_summary_stats() -> dict:
    """KPI：各层条数、快照轮次、ratio 达标视频数、批次信息。"""
    with get_connection() as conn:
        def one(sql: str, *args) -> int:
            return conn.execute(sql, args).fetchone()[0]

        return {
            "videos": one("SELECT COUNT(*) FROM videos"),
            "videos_head": one("SELECT COUNT(*) FROM videos WHERE sample_group='head'"),
            "videos_control": one("SELECT COUNT(*) FROM videos WHERE sample_group='control'"),
            "uppers": one("SELECT COUNT(*) FROM uppers"),
            "danmaku": one("SELECT COUNT(*) FROM danmaku"),
            "comments": one("SELECT COUNT(*) FROM comments"),
            "snapshot_rounds": one("SELECT COUNT(DISTINCT collect_time) FROM snapshots"),
            "danmaku_ratio_ok": one(
                "SELECT COUNT(*) FROM danmaku_fetch_log WHERE ratio >= ?",
                config.DANMAKU_RATIO_THRESHOLD),
            "last_batch": (conn.execute(
                "SELECT batch_type FROM batch_log ORDER BY end_time DESC LIMIT 1").fetchone()
                or (None,))[0],
        }


def get_batch_log() -> pd.DataFrame:
    """采集批次（采集管理页展示）。"""
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM batch_log ORDER BY end_time DESC", conn)
