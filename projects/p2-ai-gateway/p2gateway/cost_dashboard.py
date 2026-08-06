"""
Token Cost Dashboard（P2）—— 成本可视化。

不新造数据：Provider 的 usage 已带 cost_usd/latency_ms/tokens，Router 带 routing.chosen，
Cache 带 cache.status，SDK 带 version_tag。本模块做的是「观测 + 聚合 + 渲染」：
  MeteredProvider  装饰器，套最外层，每次调用把 usage 记进 tracker（看得见缓存/选型最终态）
  CostTracker      累积记录 + 按 provider/版本/缓存多维聚合 + 算缓存省下的成本
  render_dashboard 把聚合结果渲染成文本面板（stdlib，无绘图依赖）

核心 ROI 指标：缓存命中省了多少钱——命中时 actual=0、saved=这条本来要花的成本。
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class UsageRecord:
    """一次调用的成本切片（从 usage 里抽出来的可聚合字段）。"""

    provider: str
    version_tag: str | None
    prompt_tokens: int
    completion_tokens: int
    listed_cost: float          # 这条调用的名义成本（cached 命中时=省下的）
    actual_cost: float          # 实付成本（命中=0）
    latency_ms: float
    cache_status: str           # hit | miss | none

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def record_from_usage(usage: dict[str, Any], provider: str) -> UsageRecord:
    """从一个 resp.usage 提取成本切片。命中则实付 0、名义成本记为省下的。"""
    cache = usage.get("cache") or {}
    status = cache.get("status", "none")
    listed = float(usage.get("cost_usd") or 0.0)
    actual = 0.0 if status == "hit" else listed
    return UsageRecord(
        provider=provider,
        version_tag=usage.get("version_tag"),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        listed_cost=listed,
        actual_cost=actual,
        latency_ms=float(usage.get("latency_ms") or 0.0),
        cache_status=status,
    )


def _empty_bucket() -> dict[str, float]:
    """一个聚合桶的零值（所有维度共用同一套指标口径）。"""
    return {
        "reqs": 0.0,
        "prompt_tokens": 0.0,
        "completion_tokens": 0.0,
        "tokens": 0.0,
        "listed": 0.0,
        "actual": 0.0,
        "saved": 0.0,
        "latency_sum": 0.0,
        "hits": 0.0,
    }


def _accumulate(bucket: dict[str, float], r: UsageRecord) -> None:
    """把一条记录累加进桶。saved 只在命中时计（命中实付 0，名义即省下）。"""
    bucket["reqs"] += 1
    bucket["prompt_tokens"] += r.prompt_tokens
    bucket["completion_tokens"] += r.completion_tokens
    bucket["tokens"] += r.total_tokens
    bucket["listed"] += r.listed_cost
    bucket["actual"] += r.actual_cost
    bucket["latency_sum"] += r.latency_ms
    if r.cache_status == "hit":
        bucket["saved"] += r.listed_cost
        bucket["hits"] += 1


def _finalize(bucket: dict[str, float]) -> dict[str, Any]:
    """桶 → 可读指标：补 avg_ms / hit_rate / 成本四舍五入（钱留 6 位，别丢精度）。"""
    reqs = bucket["reqs"] or 1.0
    return {
        "reqs": int(bucket["reqs"]),
        "prompt_tokens": int(bucket["prompt_tokens"]),
        "completion_tokens": int(bucket["completion_tokens"]),
        "tokens": int(bucket["tokens"]),
        "listed": round(bucket["listed"], 6),
        "actual": round(bucket["actual"], 6),
        "saved": round(bucket["saved"], 6),
        "avg_ms": round(bucket["latency_sum"] / reqs, 1),
        "hits": int(bucket["hits"]),
        "hit_rate": round(bucket["hits"] / reqs, 4),
    }


@dataclass
class CostTracker:
    """
    成本账本：累积 UsageRecord + 多维聚合。

    维度口径统一（都用同一套 _finalize 指标），差别只在分组键：
      by_provider() 按最终执行的模型（Router 选型后的 routing.chosen）
      by_version()  按 prompt 版本 tag（定位「哪版 prompt 在烧钱」）
      by_cache()    按 hit/miss（算缓存 ROI 的原始切面）
    """

    records: list[UsageRecord] = field(default_factory=list)

    def add(self, record: UsageRecord) -> UsageRecord:
        self.records.append(record)
        return record

    def add_usage(self, usage: dict[str, Any], provider: str) -> UsageRecord:
        """便捷入口：直接吃一个 resp.usage。"""
        return self.add(record_from_usage(usage, provider))

    def _group(self, key: Callable[[UsageRecord], str]) -> dict[str, dict[str, Any]]:
        """按 key 分组聚合，按实付成本降序（谁烧钱谁排前面），同额按名字稳定。"""
        buckets: dict[str, dict[str, float]] = defaultdict(_empty_bucket)
        for r in self.records:
            _accumulate(buckets[key(r)], r)
        rows = {k: _finalize(v) for k, v in buckets.items()}
        return dict(sorted(rows.items(), key=lambda kv: (-kv[1]["actual"], kv[0])))

    def by_provider(self) -> dict[str, dict[str, Any]]:
        return self._group(lambda r: r.provider)

    def by_version(self) -> dict[str, dict[str, Any]]:
        return self._group(lambda r: r.version_tag or "(untagged)")

    def by_cache(self) -> dict[str, dict[str, Any]]:
        return self._group(lambda r: r.cache_status)

    def totals(self) -> dict[str, Any]:
        """总账：实付 / 名义 / 省下 + 节省率 + 命中率。空账本不炸，返回零值。"""
        bucket = _empty_bucket()
        for r in self.records:
            _accumulate(bucket, r)
        out = _finalize(bucket)
        listed = bucket["listed"]
        out["save_rate"] = round(bucket["saved"] / listed, 4) if listed else 0.0
        return out


def _attributed_provider(resp: dict[str, Any]) -> str:
    """
    成本归因到谁：优先 routing.chosen（Router 的最终选型），退回 resp.provider。

    为什么优先 routing.chosen：缓存命中返回的是**旧响应的拷贝**，里面的 provider 就是
    当初真实执行的那个模型——归因必须落在它头上，否则「哪个模型在烧钱」会算错。
    """
    usage = resp.get("usage") or {}
    routing = usage.get("routing") or {}
    return str(routing.get("chosen") or resp.get("provider") or "unknown")


@dataclass
class MeteredProvider:
    """
    采集装饰器：实现 LLMProvider.chat 契约，**套在最外层**（Metered→Cache→Router→Provider）。

    为什么必须最外层（design doc 第 6 节踩坑点）：cost_usd 由 Provider 写、cache.status 由
    Cache 写、routing.chosen 由 Router 写，全都要等下游执行完才在 usage 里齐全。套在 Cache
    里面 → 命中的请求根本不会流过来，缓存省下多少钱直接算不出。

    透传原则：kwargs 一律原样传给下游（含 version_tag），本层只读 usage、不改语义。
    """

    inner: Any                                     # 下游 LLMProvider（CachedProvider/Router/...）
    tracker: CostTracker = field(default_factory=CostTracker)
    name: str = "metered"

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        resp = self.inner.chat(messages, **kwargs)
        usage = resp.get("usage") or {}
        self.tracker.add(record_from_usage(usage, _attributed_provider(resp)))
        return resp

    def dashboard(self, title: str = "Token Cost Dashboard") -> str:
        """便捷出口：直接渲染自己 tracker 的面板。"""
        return render_dashboard(self.tracker, title=title)


# --------------------------- 渲染层（纯 stdlib，无绘图依赖）---------------------------

def _dwidth(text: str) -> int:
    """
    终端显示宽度：CJK 全角字符占 2 格，ASCII 占 1 格。

    坑：直接用 len() 算宽度，含中文的表格会错位（len("命中")=2 但终端占 4 格）。
    unicodedata.east_asian_width 返回 W/F 的即全角。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    """按显示宽度补空格（替代 str.ljust/rjust——它们按 len 算，中文会错）。"""
    gap = max(0, width - _dwidth(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def _money(v: float) -> str:
    """成本展示：小额保留 6 位（教学量级很小，2 位会全变 $0.00）。"""
    return f"${v:.6f}"


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _table(headers: list[tuple[str, int, str]], rows: list[list[str]]) -> list[str]:
    """
    渲染一张对齐表：headers = [(标题, 宽度, 对齐)]。

    返回行列表（不含外框），由 render_dashboard 统一套边框。
    """
    head = " ".join(_pad(h, w, a) for h, w, a in headers)
    lines = [head, "─" * _dwidth(head)]
    for row in rows:
        lines.append(" ".join(
            _pad(cell, w, a) for cell, (_, w, a) in zip(row, headers)
        ))
    return lines


def render_dashboard(tracker: CostTracker, title: str = "Token Cost Dashboard") -> str:
    """
    把聚合结果渲染成文本面板：总账 + 缓存节省 + 按模型 / 按 prompt 版本两张表。

    空账本不炸（返回一句 no data），这是渲染层的最低契约。
    """
    t = tracker.totals()
    if not tracker.records:
        return f"┌── {title} ──┐\n  (no data)\n└{'─' * (_dwidth(title) + 8)}┘"

    body: list[str] = [
        f"总请求 {t['reqs']} | 总 token {t['tokens']:,} | "
        f"实付 {_money(t['actual'])} | 名义 {_money(t['listed'])}",
        f"缓存节省 {_money(t['saved'])} ({_pct(t['save_rate'])}) | "
        f"命中率 {_pct(t['hit_rate'])} | 平均延迟 {t['avg_ms']}ms",
        "",
    ]

    # by model：定位哪个模型在烧钱
    body.append("by model")
    body += _table(
        [("name", 16, "left"), ("reqs", 5, "right"), ("tokens", 8, "right"),
         ("actual$", 11, "right"), ("avg_ms", 7, "right")],
        [[name, str(m["reqs"]), f"{m['tokens']:,}", _money(m["actual"]), f"{m['avg_ms']:g}"]
         for name, m in tracker.by_provider().items()],
    )
    body.append("")

    # by prompt version：定位哪版 prompt 在烧钱
    total_actual = t["actual"] or 1.0
    body.append("by prompt version")
    body += _table(
        [("tag", 16, "left"), ("reqs", 5, "right"), ("actual$", 11, "right"),
         ("share", 7, "right")],
        [[tag, str(m["reqs"]), _money(m["actual"]), _pct(m["actual"] / total_actual)]
         for tag, m in tracker.by_version().items()],
    )
    body.append("")

    # by cache：命中/未命中的原始切面（缓存 ROI 的证据）
    body.append("by cache")
    body += _table(
        [("status", 16, "left"), ("reqs", 5, "right"), ("listed$", 11, "right"),
         ("actual$", 11, "right")],
        [[st, str(m["reqs"]), _money(m["listed"]), _money(m["actual"])]
         for st, m in tracker.by_cache().items()],
    )

    inner = max(_dwidth(line) for line in body + [title])
    top = f"┌─ {title} " + "─" * max(0, inner - _dwidth(title) - 3) + "┐"
    out = [top] + [f"│ {_pad(line, inner)} │" for line in body] + ["└" + "─" * (inner + 2) + "┘"]
    return "\n".join(out)
