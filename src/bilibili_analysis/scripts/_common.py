"""采集公共层（scripts 内部共享）。

封装 B站公开 Web 接口的通用能力：会话初始化（buvid3）、wbi 签名、
全局限速、请求重试与指数退避、原始 JSON 落盘、异常日志。
供 crawler / ugc_crawler / snapshot / sync 复用，避免各脚本重复实现同一套风控。

风控三段各防什么：
- buvid3：设备级匿名标识，稳定客户端身份，避免被当作异常来源；
- wbi 签名：对参数签名，适配 B站对部分接口（UP主投稿等）的校验；
- 限速 + 退避：控制请求频率，命中风控码时冷却重试，避免被封禁。
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from bilibili_analysis.core.config import (
    RAW_DIR,
    REQUEST_INTERVAL_MAX,
    REQUEST_INTERVAL_MIN,
    SESSDATA,
)

# 统一请求头（风控基础：UA + Referer）
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

# wbi 固定重排表（公开规则）：img_key + sub_key 混排后取前 32 位作 mixin_key
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# 风控返回码：命中时触发冷却退避
_RISK_CODES = {-799, -412}

# 全局限速状态：上一次请求完成的时间戳（进程内共享）
_last_request_ts = 0.0

_LOG_FILE = RAW_DIR / "crawl.log"


def now_str() -> str:
    """当前时间字符串，统一 `YYYY-MM-DD HH:MM:SS`（秒级，不截断到日期）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    """打印并追加一行到 data/raw/crawl.log（带时间戳）。"""
    line = f"[{now_str()}] {msg}"
    print(line)
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # 日志写入失败不阻断采集


def make_session(with_sessdata: bool = False) -> requests.Session:
    """创建带统一请求头与 buvid3 的会话。

    登录态会话额外写入 SESSDATA（仅本地，不入库不入仓），并主动访问
    主站获取 buvid3——wbi 接口（UP主投稿等）需要 buvid3 + 登录态两者兼备，
    仅靠 nav 接口回写 buvid3 在本环境不可靠（nav 返回 -101 时不设置）。
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    if with_sessdata and SESSDATA:
        session.cookies.set("SESSDATA", SESSDATA, domain=".bilibili.com")
        try:
            session.get("https://www.bilibili.com/", timeout=15)
        except Exception:
            pass
    return session


def _throttle() -> None:
    """全局限速：保证相邻请求间隔落在配置区间内（进程内共享）。"""
    global _last_request_ts
    if REQUEST_INTERVAL_MIN <= 0:
        return
    elapsed = time.time() - _last_request_ts
    interval = random.uniform(REQUEST_INTERVAL_MIN, REQUEST_INTERVAL_MAX)
    if elapsed < interval:
        time.sleep(interval - elapsed)
    _last_request_ts = time.time()


def _extract_wbi_keys(session: requests.Session) -> tuple[str, str] | None:
    """从 nav 接口提取 wbi 的 img_key / sub_key（未登录也可取到）。"""
    try:
        resp = session.get("https://api.bilibili.com/x/web-interface/nav", timeout=15)
        data = (resp.json().get("data") or {})
        wbi = data.get("wbi_img") or {}
        img_key = (wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
        sub_key = (wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
        if img_key and sub_key:
            return img_key, sub_key
    except Exception:
        pass
    return None


def _mixin_key(img_key: str, sub_key: str) -> str:
    """按公开重排表计算 mixin_key（取混排后前 32 位）。"""
    raw = img_key + sub_key
    return "".join(raw[i] for i in _MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def sign_wbi(params: dict[str, Any], img_key: str, sub_key: str) -> dict[str, Any]:
    """对参数做 wbi 签名，返回追加了 wts 与 w_rid 的新参数字典。"""
    mixin = _mixin_key(img_key, sub_key)
    signed = dict(params)
    signed["wts"] = round(time.time())
    signed = dict(sorted(signed.items()))
    # 过滤 wbi 签名约定排除的字符
    cleaned = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in signed.items()
    }
    query = urlencode(cleaned)
    signed["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return signed


def http_get(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None = None,
    *,
    wbi: bool = False,
    retries: int = 3,
    timeout: int = 15,
) -> dict[str, Any] | None:
    """带限速、重试与退避的 GET 请求，返回解析后的 JSON 或 None。

    命中风控码（-799 / -412）时按指数退避重试；多次失败返回 None，
    不抛异常中断整条采集任务。业务错误码（如 -101）返回原始结构供上层判断。
    """
    params = dict(params or {})
    for attempt in range(retries):
        _throttle()
        try:
            req_params = dict(params)
            if wbi:
                keys = _extract_wbi_keys(session)
                if keys:
                    req_params = sign_wbi(req_params, keys[0], keys[1])
            resp = session.get(url, params=req_params, timeout=timeout)
            data = resp.json()
            code = data.get("code")
            if code == 0:
                # wbi 投稿等接口被风控时 code 仍为 0，但 data 只含 v_voucher
                body = data.get("data")
                if isinstance(body, dict) and "v_voucher" in body:
                    time.sleep(2 ** attempt)
                    continue
                return data
            if code in _RISK_CODES:
                time.sleep(2 ** attempt)
                continue
            return data
        except Exception:
            time.sleep(2 ** attempt)
    return None


def save_raw(name: str, data: Any) -> Path:
    """原始 JSON 落盘到 data/raw/（UTF-8，ensure_ascii=False），自动建子目录。"""
    path = RAW_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
