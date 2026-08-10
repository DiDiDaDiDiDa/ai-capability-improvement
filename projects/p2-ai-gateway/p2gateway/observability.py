"""
Observability（P2 M9）—— Tracing + Metrics。

三大支柱：Tracing「单请求经过哪些环节、各花多久」（span 树），Metrics「整体量/延迟/错误/
成本趋势」（时序聚合），Logging「出事翻细节」。三者用 trace_id 串联。Gateway 是天然汇聚点
——所有请求都过它，埋一层即全链路可见。

关键设计：
  - 延迟用**分位数 p50/p95/p99 不用均值**——均值被拉平掩盖长尾，p95/p99 才反映尾延迟体感。
  - 复用已有 usage（cost/cache/routing/version_tag）直接进 metrics labels 和 span attrs，不重采。
  - TracedProvider 包最外层各开 span 共享 trace_id → 完整链路视图。

诚实边界（第 5 节）：教学是**进程内** span/metric 收集 + 文本渲染。生产是一套基础设施
（OTel→Jaeger、Prometheus→Grafana、结构化日志→Loki），本模块是接入前的方法内核骨架，
**不声称是生产级可观测性**。
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Span:
    name: str
    trace_id: str
    duration_ms: float
    status: str                              # ok | error
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricsRegistry:
    """进程内指标收集：counter（计数）+ 延迟样本（算分位数）。"""

    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def inc(self, name: str, labels: dict[str, Any] | None = None, value: float = 1.0) -> None:
        self.counters[self._key(name, labels)] += value

    def observe_latency(self, provider: str, ms: float) -> None:
        self.latencies[provider].append(ms)

    @staticmethod
    def _key(name: str, labels: dict[str, Any] | None) -> str:
        if not labels:
            return name
        tag = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{tag}}}"

    @staticmethod
    def _percentile(samples: list[float], p: float) -> float:
        """线性插值分位数。空样本返回 0。"""
        if not samples:
            return 0.0
        s = sorted(samples)
        if len(s) == 1:
            return round(s[0], 1)
        rank = (len(s) - 1) * p
        lo = int(rank)
        frac = rank - lo
        hi = min(lo + 1, len(s) - 1)
        return round(s[lo] + (s[hi] - s[lo]) * frac, 1)

    def latency_stats(self, provider: str) -> dict[str, float]:
        s = self.latencies.get(provider, [])
        return {
            "count": len(s),
            "p50": self._percentile(s, 0.50),
            "p95": self._percentile(s, 0.95),
            "p99": self._percentile(s, 0.99),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "latency": {p: self.latency_stats(p) for p in self.latencies},
        }


@dataclass
class TracedProvider:
    """
    Tracing + Metrics 装饰器：实现 chat 契约，包最外层（或每层各开 span 共享 trace_id）。

    每次 chat 开一个 span 记 name/duration/status/attributes，并把延迟、请求数、错误数
    打进 metrics。复用 usage 里的 provider/cache/version_tag 做 labels 和 span attrs。
    回填 usage.trace = {trace_id, spans:[...]}，便于单请求下钻调试。
    """

    inner: Any
    metrics: MetricsRegistry = field(default_factory=MetricsRegistry)
    span_name: str = "gateway.request"
    now_ms: Callable[[], float] = lambda: time.monotonic() * 1000.0
    name: str = "traced"
    spans: list[Span] = field(default_factory=list)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        trace_id = kwargs.pop("trace_id", None) or uuid.uuid4().hex[:12]
        t0 = self.now_ms()
        status = "ok"
        resp: dict[str, Any] = {}
        try:
            resp = self.inner.chat(messages, **kwargs)
            return self._finish(resp, trace_id, t0, status="ok")
        except Exception:
            status = "error"
            self._finish({}, trace_id, t0, status="error")
            raise

    def _finish(self, resp: dict[str, Any], trace_id: str, t0: float, status: str) -> dict[str, Any]:
        dur = round(self.now_ms() - t0, 2)
        usage = resp.get("usage") or {}
        provider = (usage.get("routing") or {}).get("chosen") or resp.get("provider") or "unknown"
        attrs = {
            "provider": provider,
            "cache": (usage.get("cache") or {}).get("status"),
            "version_tag": usage.get("version_tag"),
            "cost_usd": usage.get("cost_usd"),
        }
        span = Span(self.span_name, trace_id, dur, status, {k: v for k, v in attrs.items() if v is not None})
        self.spans.append(span)

        labels = {"provider": provider, "status": status}
        self.metrics.inc("requests", labels)
        if status == "error":
            self.metrics.inc("errors", {"provider": provider})
        else:
            self.metrics.observe_latency(provider, dur)

        if status == "ok":
            u = dict(usage)
            u["trace"] = {"trace_id": trace_id, "spans": [
                {"name": span.name, "duration_ms": span.duration_ms,
                 "status": span.status, "attributes": span.attributes}]}
            resp["usage"] = u
        return resp

    def render_metrics(self) -> str:
        """文本快照：请求/错误计数 + 各 provider 的 p50/p95/p99。"""
        snap = self.metrics.snapshot()
        lines = ["📈 Metrics 快照"]
        for k, v in sorted(snap["counters"].items()):
            lines.append(f"  {k} = {v:g}")
        lines.append("  latency (ms):")
        for prov, st in sorted(snap["latency"].items()):
            lines.append(f"    {prov:16s} n={st['count']} p50={st['p50']} p95={st['p95']} p99={st['p99']}")
        return "\n".join(lines)
