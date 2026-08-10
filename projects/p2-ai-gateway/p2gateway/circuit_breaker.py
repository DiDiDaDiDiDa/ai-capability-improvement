"""
Circuit Breaker（P2 M6）—— 给每个 Provider 装保险丝，把「慢失败」变「快失败」。

底层逻辑（和 Retry 分工）：Retry/Fallback 是「出错了怎么补救」，熔断是「别再撞已知的墙」。
一个 Provider 已经持续挂了，还对它 Retry 3 次 × 每次超时 = 白等；熔断跳闸后**立即**失败
转 Fallback，保护整体延迟和资源。

三态机：
  Closed    正常放行，统计滑动窗口失败率；失败率超阈 → Open
  Open      直接拒绝（快速失败），不调 Provider；到冷却时间 → Half-Open
  Half-Open 只放少量探针；探针成功 → Closed（恢复），探针失败 → Open（重新计时）

关键设计：**每 Provider 一个 breaker**（全局一个会一挂误伤全部）；冷却时间需按恢复特征调
（太短刚恢复被打回，太长好了还被拒）；Half-Open 只放少量探针（防未恢复被探针洪水二次打死）。
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

State = Literal["closed", "open", "half_open"]


@dataclass
class CircuitBreaker:
    """
    单个 Provider 的熔断器。时间注入用 `now`（默认 time.monotonic），便于测试不 sleep。

    参数：
      window_size       滑动窗口大小（最近 N 次调用）
      failure_threshold 窗口内失败率达到该值即跳闸（如 0.5）
      min_calls         窗口内至少这么多次调用才评估失败率（防冷启动一两次失败就跳）
      cooldown_s        Open 持续多久转 Half-Open
      half_open_probes  Half-Open 放行的探针数
    """

    window_size: int = 20
    failure_threshold: float = 0.5
    min_calls: int = 5
    cooldown_s: float = 30.0
    half_open_probes: int = 1
    now: "callable" = field(default=time.monotonic)  # type: ignore[name-defined]

    state: State = field(default="closed", init=False)
    _window: deque[bool] = field(default_factory=deque, init=False)  # True=失败
    _opened_at: float = field(default=0.0, init=False)
    _probes_left: int = field(default=0, init=False)

    def _failure_rate(self) -> float:
        if not self._window:
            return 0.0
        return sum(self._window) / len(self._window)

    def allow(self) -> bool:
        """能否放行一次调用。Open 且未到冷却 → False（快速失败）；到冷却自动转 Half-Open。"""
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.now() - self._opened_at >= self.cooldown_s:
                self.state = "half_open"
                self._probes_left = self.half_open_probes
                return True
            return False
        # half_open：只放剩余探针数
        if self._probes_left > 0:
            self._probes_left -= 1
            return True
        return False

    def record(self, success: bool) -> None:
        """记录一次调用结果并做状态转移。"""
        if self.state == "half_open":
            if success:
                self._reset_closed()          # 探针成功 → 恢复
            else:
                self._trip_open()             # 探针失败 → 重新跳闸计时
            return
        # closed：进窗口，达标则评估失败率
        self._window.append(not success)
        while len(self._window) > self.window_size:
            self._window.popleft()
        if len(self._window) >= self.min_calls and self._failure_rate() >= self.failure_threshold:
            self._trip_open()

    def _trip_open(self) -> None:
        self.state = "open"
        self._opened_at = self.now()
        self._window.clear()

    def _reset_closed(self) -> None:
        self.state = "closed"
        self._window.clear()
        self._probes_left = 0

    def snapshot(self) -> dict[str, object]:
        return {"state": self.state, "failure_rate": round(self._failure_rate(), 4),
                "window": len(self._window)}


class BreakerRegistry:
    """每 Provider 一个 breaker 的注册表——按名字取，第一次访问懒创建（共享同一套参数）。"""

    def __init__(self, **breaker_kwargs) -> None:
        self._kwargs = breaker_kwargs
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(**self._kwargs)
        return self._breakers[name]

    def states(self) -> dict[str, str]:
        return {name: b.state for name, b in self._breakers.items()}
