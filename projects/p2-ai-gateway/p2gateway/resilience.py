"""
Fallback + Retry（P2 M5）—— Provider 故障兜底。

分工（别混）：
  Retry     处理**同一 Provider 的瞬时抖动**（超时/429/5xx，退避重试同一个）
  Fallback  处理**某 Provider 整体不可用**（重试耗尽 → 切下一个候选）

关键：不是所有错误都该重试。4xx（参数错、内容违规）重试也没用——只有瞬时类
（RetryableError）才重试；重试耗尽再 Fallback。全部候选挂完才抛 AllProvidersFailed。

与熔断咬合：每个候选调用前先问 breaker.allow()，跳闸的直接跳过（等价 Fallback 到下一个），
调用后 breaker.record(成功与否)。这样「熔断 + Fallback + Router」三者天然咬合。
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .circuit_breaker import BreakerRegistry


class RetryableError(RuntimeError):
    """瞬时故障（超时/429/5xx）——应退避重试同一 Provider。"""


class FatalError(RuntimeError):
    """不可重试故障（4xx/参数/违规）——重试无用，直接换下一个候选。"""


class AllProvidersFailed(RuntimeError):
    """所有候选都失败——兜底也兜不住，才向上抛。"""


def _provider_name(p: Any) -> str:
    prof = getattr(p, "profile", None)
    return getattr(prof, "name", None) or getattr(p, "name", None) or p.__class__.__name__


@dataclass
class ResilientProvider:
    """
    实现 chat 契约的装饰器：持有一组候选 Provider，按序做 Retry + Fallback。

    退避：指数退避 + 抖动（base * 2^attempt + rand），避免重试风暴。
    归因：回填 usage.resilience = {attempts, fell_back_to, tried:[...]}，重试/降级路径可观测。
    熔断：传入 breakers 时，每候选调用前查 allow()、调用后 record()。
    """

    candidates: list[Any]
    max_retries: int = 3                 # 单个候选最多尝试次数（含首次）
    base_backoff_s: float = 0.05
    breakers: BreakerRegistry | None = None
    sleep: Callable[[float], None] = time.sleep
    rand: Callable[[], float] = random.random
    name: str = "resilient"

    def _backoff(self, attempt: int) -> float:
        return self.base_backoff_s * (2 ** attempt) + self.rand() * self.base_backoff_s

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        tried: list[str] = []
        total_attempts = 0
        last_err: Exception | None = None

        for provider in self.candidates:
            name = _provider_name(provider)
            breaker = self.breakers.get(name) if self.breakers else None

            if breaker is not None and not breaker.allow():
                tried.append(f"{name}:circuit_open")   # 跳闸 → 快速跳过，等价 Fallback
                continue

            tried.append(name)
            for attempt in range(self.max_retries):
                total_attempts += 1
                try:
                    resp = provider.chat(messages, **kwargs)
                    if breaker is not None:
                        breaker.record(success=True)
                    usage = dict(resp.get("usage") or {})
                    usage["resilience"] = {
                        "attempts": total_attempts,
                        "fell_back_to": name if name != _provider_name(self.candidates[0]) else None,
                        "tried": tried,
                    }
                    resp["usage"] = usage
                    return resp
                except RetryableError as e:
                    last_err = e
                    if breaker is not None:
                        breaker.record(success=False)
                    if attempt < self.max_retries - 1:
                        self.sleep(self._backoff(attempt))   # 退避后重试同一候选
                    # 重试耗尽 → 跳出内层，进入下一个候选（Fallback）
                except FatalError as e:
                    last_err = e
                    if breaker is not None:
                        breaker.record(success=False)
                    break                                    # 不可重试 → 直接换候选

        raise AllProvidersFailed(
            f"all candidates failed; tried={tried}; last_error={last_err!r}"
        )
