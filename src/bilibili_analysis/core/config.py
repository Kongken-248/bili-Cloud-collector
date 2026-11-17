"""全局配置：从 .env 读取 + 项目路径常量。

设计约定（总纲第四节）：
- 所有配置项集中在本文件，代码中不硬编码路径与密钥。
- SESSDATA 与大模型 key 不入库、不入仓库。
- 其余文件一律从 config.PROJECT_ROOT 派生路径，不自行拼路径。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 项目路径（全项目唯一写法）
# 本文件位于 src/bilibili_analysis/core/config.py，
# parents[0]=core, parents[1]=bilibili_analysis, parents[2]=src, parents[3]=项目根。
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "bilibili.db"
DOCS_DIR = PROJECT_ROOT / "docs"

# 加载 .env（不存在则跳过，全部配置走默认值）
load_dotenv(PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# 类型安全读取辅助
# ---------------------------------------------------------------------------
def _get_bool(name: str, default: bool = False) -> bool:
    """读取布尔型环境变量，接受 1/true/yes/on（大小写不敏感）。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    """读取浮点型环境变量，缺省或解析失败返回默认值。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    """读取整型环境变量，缺省或解析失败返回默认值。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# B站公开接口
# ---------------------------------------------------------------------------
BILI_API_BASE: str = os.getenv("BILI_API_BASE", "https://api.bilibili.com").rstrip("/")


# 新版排行榜分区名单：分区名 → tid。
# tname 以此名单为准，不使用接口返回名（数据字典第 2 节口径）。
# 默认六区已确认：游戏/动画/知识/美食/影视/科技数码。
PARTITIONS: dict[str, int] = {
    "游戏": 1008,
    "动画": 1005,
    "知识": 1010,
    "美食": 1020,
    "影视": 1001,
    "科技数码": 1012,
}

# 请求间隔（秒）：全局限速，请求在 [MIN, MAX] 区间随机等待
REQUEST_INTERVAL_MIN: float = _get_float("REQUEST_INTERVAL_MIN", 1.5)
REQUEST_INTERVAL_MAX: float = _get_float("REQUEST_INTERVAL_MAX", 3.0)
RETRY_TIMES: int = _get_int("RETRY_TIMES", 3)

# 评论封顶条数 N：每视频仅采一级热评（主楼）
COMMENT_CAP_N: int = _get_int("COMMENT_CAP_N", 200)

# 弹幕对账 ratio 阈值：低于该值的视频在时间分布类分析中剔除或标注
DANMAKU_RATIO_THRESHOLD: float = _get_float("DANMAKU_RATIO_THRESHOLD", 0.8)

# UP主回查降级触发阈值
UP_DEGRADE_TIME_LIMIT: float = _get_float("UP_DEGRADE_TIME_LIMIT", 3600)
UP_DEGRADE_RISK_LIMIT: int = _get_int("UP_DEGRADE_RISK_LIMIT", 5)

# ---------------------------------------------------------------------------
# 登录态（仅本地，不入库不入仓）
# ---------------------------------------------------------------------------
SESSDATA: str = os.getenv("SESSDATA", "").strip()
BUVID3: str = os.getenv("BUVID3", "").strip()

# ---------------------------------------------------------------------------
# 大模型（OpenAI 兼容接口，默认留空 = 未配置）
# ---------------------------------------------------------------------------
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "").strip()
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL: str = os.getenv("LLM_MODEL", "").strip()
LLM_OFFLINE: bool = _get_bool("LLM_OFFLINE", False)


def is_llm_configured() -> bool:
    """判断大模型三项是否配置齐全（base_url / api_key / model 均非空）。"""
    return bool(LLM_BASE_URL and LLM_API_KEY and LLM_MODEL)
