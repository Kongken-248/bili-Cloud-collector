"""大模型调用层（OpenAI 兼容 HTTP API）。

三处防御（提示词硬要求，缺一不可）：
1. 未配置防御：base_url / api_key / model 三项未配齐时直接返回降级结果，不发请求；
2. 离线开关：LLM_OFFLINE=1 强制离线模式（界面统计照常，AI 功能提示不可用）；
3. 超时/重试/异常防御：请求超时自动重试（指数退避），最终失败返回结构化
   LLMResult(ok=False + 错误原因)，全程不抛异常，界面不会白屏。

审计：每次调用（无论成败）追加记录到 data/llm_calls.csv，供论文「AI 使用范围」引用。
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from bilibili_analysis.core.config import (
    DATA_DIR,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_OFFLINE,
    is_llm_configured,
)

_CALL_LOG = DATA_DIR / "llm_calls.csv"

# 审计 CSV 列（固定，便于后期 pandas 读取）
_LOG_FIELDS = ["timestamp", "scene", "model", "prompt_chars", "elapsed_sec",
               "ok", "total_tokens", "error"]


@dataclass
class LLMResult:
    """结构化调用结果：永不抛异常，失败时 ok=False 并带可读错误原因。"""

    ok: bool
    content: str = ""
    elapsed: float = 0.0
    error: str = ""
    usage: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """本次调用消耗的总 token 数（无则 0）。"""
        return int((self.usage or {}).get("total_tokens") or 0)


def _log_call(scene: str, prompt_chars: int, elapsed: float,
              ok: bool, tokens: int = 0, error: str = "") -> None:
    """追加一条审计记录（CSV；写入失败静默，不影响主流程）。"""
    try:
        _CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        new_file = not _CALL_LOG.exists()
        with _CALL_LOG.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_LOG_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "scene": scene, "model": LLM_MODEL or "",
                "prompt_chars": prompt_chars,
                "elapsed_sec": round(elapsed, 2), "ok": int(ok),
                "total_tokens": tokens, "error": error[:120],
            })
    except OSError:
        pass


def chat(prompt: str, *, temperature: float = 0.3, timeout: int = 30,
         retries: int = 2, scene: str = "chat",
         max_tokens: int | None = None) -> LLMResult:
    """统一入口：OpenAI 兼容 /chat/completions 调用。

    参数：
        prompt：完整提示词（含注入的数据文本）。
        temperature：生成温度，分析场景默认 0.3（克制）。
        timeout / retries：单次请求超时秒数与重试次数（指数退避）。
        scene：调用场景名（写入审计日志，便于区分局部解读/综合报告等）。
        max_tokens：可选输出上限；None 表示不限制。
    """
    # 防御 1：离线开关
    if LLM_OFFLINE:
        err = "离线模式已开启（LLM_OFFLINE=1），AI 功能不可用"
        _log_call(scene, len(prompt), 0.0, False, error=err)
        return LLMResult(ok=False, error=err)
    # 防御 2：配置不齐
    if not is_llm_configured():
        err = "大模型未配置（.env 缺 LLM_BASE_URL/API_KEY/MODEL）"
        _log_call(scene, len(prompt), 0.0, False, error=err)
        return LLMResult(ok=False, error=err)

    payload: dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    last_err = ""
    for attempt in range(retries + 1):
        start = time.time()
        try:
            resp = requests.post(
                f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json=payload, timeout=timeout,
            )
            elapsed = time.time() - start
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}: {resp.text[:120]}"
            else:
                data = resp.json()
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                usage = data.get("usage") or {}
                _log_call(scene, len(prompt), elapsed, True,
                          int(usage.get("total_tokens") or 0))
                return LLMResult(ok=bool(content), content=content, elapsed=elapsed,
                                 error="" if content else "返回内容为空", usage=usage)
        except Exception as e:  # 网络错误 / 超时 / JSON 解析失败等
            elapsed = time.time() - start
            last_err = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(2 ** attempt)  # 指数退避：1s、2s
    # 防御 3：最终失败 → 结构化结果
    _log_call(scene, len(prompt), time.time() - start, False, error=last_err)
    return LLMResult(ok=False, error=f"重试 {retries + 1} 次后失败：{last_err}",
                     elapsed=time.time() - start)


def batch_chat(prompts: list[str], *,
               progress: Callable[[int, int], None] | None = None,
               stop_on_error: bool = False,
               **kwargs: Any) -> list[LLMResult]:
    """串行批量调用，progress(done, total) 进度回调（供页面进度条使用）。

    stop_on_error=False 时单条失败不中断批次（结果中 ok=False 留痕）。
    """
    results: list[LLMResult] = []
    for i, p in enumerate(prompts):
        results.append(chat(p, scene="batch", **kwargs))
        if progress:
            progress(i + 1, len(prompts))
        if stop_on_error and not results[-1].ok:
            break
    return results
