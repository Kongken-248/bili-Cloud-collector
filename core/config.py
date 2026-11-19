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
# 本文件位于 core/config.py，
# parents[0]=core, parents[1]=项目根。
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 新位置：core/ 上一级 = 项目根

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLOUD_DIR = DATA_DIR / "cloud"
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
# 快照轮默认 1.0~2.5s：兼顾整轮耗时（601 条约 18 分钟）与风控压力，
# 云端 workflow / 本地 .env 仍可用同名环境变量覆盖。
REQUEST_INTERVAL_MIN: float = _get_float("REQUEST_INTERVAL_MIN", 1.0)
REQUEST_INTERVAL_MAX: float = _get_float("REQUEST_INTERVAL_MAX", 2.5)
RETRY_TIMES: int = _get_int("RETRY_TIMES", 3)

# 批次间冷却（秒）：分区之间 / UP主批次之间的额外冷却（提示词 4.3）
BATCH_COOLDOWN_MIN: float = _get_float("BATCH_COOLDOWN_MIN", 30)
BATCH_COOLDOWN_MAX: float = _get_float("BATCH_COOLDOWN_MAX", 60)

# 评论封顶条数 N：每视频仅采一级热评（主楼），提示词默认 100
COMMENT_CAP_N: int = _get_int("COMMENT_CAP_N", 100)

# 弹幕对账 ratio 阈值：低于该值的视频在时间分布类分析中剔除或标注（提示词默认 0.9）
DANMAKU_RATIO_THRESHOLD: float = _get_float("DANMAKU_RATIO_THRESHOLD", 0.9)

# UP主回查降级触发阈值（提示词 4.3：任一命中即触发，并写日志）
UP_DEGRADE_TIME_LIMIT: float = _get_float("UP_DEGRADE_TIME_LIMIT", 14400)   # 预计剩余 >4 小时
UP_DEGRADE_RISK_LIMIT: int = _get_int("UP_DEGRADE_RISK_LIMIT", 10)          # 连续失败 ≥10 个
UP_DEGRADE_FAIL_RATE: float = _get_float("UP_DEGRADE_FAIL_RATE", 0.2)       # 失败率 >20%

# 冻结自检（提示词 4.3：近 7 天投稿占比 <20%，或相邻两轮重合率 >90%）
FREEZE_RECENT_DAYS: int = _get_int("FREEZE_RECENT_DAYS", 7)
FREEZE_RECENT_RATIO: float = _get_float("FREEZE_RECENT_RATIO", 0.2)
FREEZE_OVERLAP_RATIO: float = _get_float("FREEZE_OVERLAP_RATIO", 0.9)

# 分析层工程默认（数据字典：进度分箱 20 bins、趋同度窗口 10 秒，均为配置项）
DANMAKU_PROGRESS_BINS: int = _get_int("DANMAKU_PROGRESS_BINS", 20)
DANMAKU_SIMILARITY_WINDOW: int = _get_int("DANMAKU_SIMILARITY_WINDOW", 10)

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
