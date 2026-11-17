"""SQLite 数据访问层。

本阶段（模块 0）只负责按 docs/数据字典.md 建出全部八张空表与索引（幂等）。
查询函数（get_videos / get_delta_table 等）在模块二（清洗入库）补充。

字段口径唯一真源：docs/数据字典.md。表结构不得在此处擅自修改。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bilibili_analysis.core import config

# ---------------------------------------------------------------------------
# 建表 SQL（字段名与类型严格对齐数据字典）
# 注意：`like` 是 SQLite 关键字，作列名时用双引号包裹，查询时同理。
# ---------------------------------------------------------------------------
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
