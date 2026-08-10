"""
Rate Limit / Quota（P2 M8）—— 限流与配额。

分工：
  Rate Limit  管**瞬时速率**（每秒多少 token/请求，防突发打爆下游），Token Bucket 实现
  Quota       管**累计用量**（周期内总配额，防超预算），预估 + 事后核销

套在链路**靠前**（Guardrail 之后、Cache 之前）：超限的请求在**花钱之前**就被挡下。
按 key（api_key/user_id/tenant）分桶分配额——多租户隔离，一个租户超限不影响其他人。

诚实边界（第 3 节）：这是**单机内存**版，教学足够。多实例 Gateway 必须共享状态
（Redis 原子计数 INCR+EXPIRE / Lua），否则每实例各限各的 = 总量翻 N 倍失效——
**分布式一致性是它到生产的主要 gap**，不假装单机版能直接上多实例。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


class RateLimitExceeded(RuntimeError):
    """瞬时速率超限（桶空）。"""


class QuotaExceeded(RuntimeError):
    """累计配额耗尽。"""


@dataclass
class TokenBucket:
    """
    令牌桶：容量 capacity，按 refill_rate（个/秒）匀速补令牌。
    允许一定突发（吃桶存量），长期速率受 refill_rate 约束。时间用 now 注入，测试不 sleep。
    """

    capacity: float
    refill_rate: float
    now: Callable[[], float] = time.monotonic
    _tokens: float = field(default=0.0, init=False)
    _last: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last = self.now()

    def _refill(self) -> None:
        t = self.now()
        elapsed = t - self._last
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last = t

    def take(self, n: float) -> bool:
        """取 n 个令牌，够则扣减放行，不够则拒绝（不扣）。"""
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    def remaining(self) -> float:
        self._refill()
        return round(self._tokens, 2)


@dataclass
class Quota:
    """周期累计配额：limit 上限，used 已用。预估占额 + 事后核销真实用量。"""

    limit: float
    used: float = 0.0

    def would_exceed(self, estimate: float) -> bool:
        return self.used + estimate > self.limit

    def charge(self, actual: float) -> None:
        self.used += actual

    def remaining(self) -> float:
        return round(max(0.0, self.limit - self.used), 2)


def _est_tokens(messages: list[dict[str, str]]) -> int:
    """按 prompt 长度粗估 token（与 providers 的 len//4 同源）。生产用真 tokenizer。"""
    return max(1, sum(len(m.get("content", "")) for m in messages) // 4)


@dataclass
class RateLimitedProvider:
    """
    限流+配额装饰器：实现 chat 契约，套靠前（Cache 之前）。

    按 key 取各自的桶与配额：
      1) 按 prompt 预估 token 数 → 桶取令牌，取不到 → RateLimitExceeded（花钱前挡下）
      2) 预估是否超配额 → 超 → QuotaExceeded
      3) 调下游 → 用真实 usage.total_tokens 核销配额（补上预估与实际的差额）
    回填 usage.limit = {key, remaining_rate, remaining_quota}，调用方可感知余量自我调度。
    """

    inner: Any
    capacity: float = 100.0
    refill_rate: float = 50.0
    quota_limit: float = 10_000.0
    now: Callable[[], float] = time.monotonic
    name: str = "rate-limit"
    _buckets: dict[str, TokenBucket] = field(default_factory=dict, init=False)
    _quotas: dict[str, Quota] = field(default_factory=dict, init=False)

    def _bucket(self, key: str) -> TokenBucket:
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(self.capacity, self.refill_rate, now=self.now)
        return self._buckets[key]

    def _quota(self, key: str) -> Quota:
        if key not in self._quotas:
            self._quotas[key] = Quota(self.quota_limit)
        return self._quotas[key]

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        key = kwargs.pop("limit_key", "default")
        est = _est_tokens(messages)
        bucket, quota = self._bucket(key), self._quota(key)

        if not bucket.take(est):
            raise RateLimitExceeded(
                f"rate limit for key={key}: need {est}, remaining {bucket.remaining()}")
        if quota.would_exceed(est):
            raise QuotaExceeded(
                f"quota for key={key}: used {quota.used}+{est} > {quota.limit}")

        resp = self.inner.chat(messages, **kwargs)

        usage = dict(resp.get("usage") or {})
        actual = usage.get("total_tokens")
        if actual is None:
            actual = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        quota.charge(actual or est)          # 事后核销：用真实用量，缺失则退回预估
        usage["limit"] = {
            "key": key,
            "remaining_rate": bucket.remaining(),
            "remaining_quota": quota.remaining(),
        }
        resp["usage"] = usage
        return resp
