"""
Model Router（P2 M2）—— 按成本 / 延迟 / 能力动态选模型。

底层逻辑：
  1) 硬过滤——能力(capabilities)与上下文(max_context)是「必须满足」的门槛，不满足直接淘汰。
  2) 软排序——在候选里按策略打分选最优：
       cost     选最便宜
       latency  选最快
       quality  选最强
       balanced 归一化后按权重综合（默认成本/延迟/质量各有权重）
  3) Router 自身实现 chat 契约 → 对 P1 就是一个普通 LLMProvider（可组合、可热插）。

选完把「路由决策」回填到 usage.routing，可观测、可审计（不是黑箱选）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .providers import ScriptedProvider

Strategy = Literal["cost", "latency", "quality", "balanced"]


class RouteError(RuntimeError):
    """无候选满足硬约束（能力/上下文）时抛出——绝不静默乱选。"""


@dataclass
class RouteRequest:
    """一次请求的路由约束。"""

    messages: list[dict[str, str]]
    strategy: Strategy = "balanced"
    need_caps: set[str] = field(default_factory=set)  # 必须具备的能力
    max_cost_per_1k: float | None = None              # 成本上限（超则淘汰）
    max_latency_ms: float | None = None               # 延迟上限（超则淘汰）
    est_context: int = 0                              # 预估 token，超 max_context 淘汰


@dataclass
class RouteDecision:
    chosen: str
    strategy: str
    score: float
    candidates: list[str]
    rejected: dict[str, str]   # name -> 淘汰原因


class ModelRouter:
    """持有一组 Provider，按 RouteRequest 选一个执行。自身也是 LLMProvider。"""

    name = "model-router"

    def __init__(self, providers: list[ScriptedProvider]) -> None:
        if not providers:
            raise ValueError("router needs at least one provider")
        self.providers = providers

    # --- 硬过滤：能力 / 成本 / 延迟 / 上下文 ---
    def _filter(self, req: RouteRequest) -> tuple[list[ScriptedProvider], dict[str, str]]:
        ok: list[ScriptedProvider] = []
        rejected: dict[str, str] = {}
        for p in self.providers:
            prof = p.profile
            if not p.healthy:
                rejected[p.name] = "unhealthy"
            elif not prof.supports(req.need_caps):
                missing = req.need_caps - set(prof.capabilities)
                rejected[p.name] = f"missing_caps:{sorted(missing)}"
            elif req.est_context and req.est_context > prof.max_context:
                rejected[p.name] = f"context_over:{req.est_context}>{prof.max_context}"
            elif req.max_cost_per_1k is not None and prof.cost_per_1k > req.max_cost_per_1k:
                rejected[p.name] = f"too_expensive:{prof.cost_per_1k}>{req.max_cost_per_1k}"
            elif req.max_latency_ms is not None and prof.latency_ms > req.max_latency_ms:
                rejected[p.name] = f"too_slow:{prof.latency_ms}>{req.max_latency_ms}"
            else:
                ok.append(p)
        return ok, rejected

    # --- 软排序：按策略打分（分越高越好）---
    def _score(self, p: ScriptedProvider, strategy: Strategy, pool: list[ScriptedProvider]) -> float:
        prof = p.profile
        if strategy == "cost":
            return -prof.cost_per_1k            # 越便宜分越高
        if strategy == "latency":
            return -prof.latency_ms             # 越快分越高
        if strategy == "quality":
            return prof.quality                 # 越强分越高
        # balanced：三维 min-max 归一化后加权（成本/延迟越低越好，质量越高越好）
        costs = [x.profile.cost_per_1k for x in pool]
        lats = [x.profile.latency_ms for x in pool]
        quals = [x.profile.quality for x in pool]
        c = _norm(prof.cost_per_1k, costs, invert=True)
        l = _norm(prof.latency_ms, lats, invert=True)
        q = _norm(prof.quality, quals, invert=False)
        return 0.4 * c + 0.3 * l + 0.3 * q      # 权重可调；成本略重

    def route(self, req: RouteRequest) -> tuple[ScriptedProvider, RouteDecision]:
        """只做「选」，不执行。返回选中的 Provider + 可审计的决策记录。"""
        pool, rejected = self._filter(req)
        if not pool:
            raise RouteError(
                f"no provider satisfies constraints; rejected={rejected}"
            )
        scored = sorted(
            pool,
            key=lambda p: (-self._score(p, req.strategy, pool), p.name),  # 分高优先，名字兜底稳定
        )
        best = scored[0]
        decision = RouteDecision(
            chosen=best.name,
            strategy=req.strategy,
            score=round(self._score(best, req.strategy, pool), 4),
            candidates=[p.name for p in scored],
            rejected=rejected,
        )
        return best, decision

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        """LLMProvider 契约：选型 → 委托执行 → 回填路由决策到 usage.routing。

        version_tag：应用层 SDK 传下来的不透明版本标签（如 "qa@v1"），Router 只做归因、
        不解析——保持 prompt-agnostic。stamp 进 usage.version_tag，与成本/延迟同处便于关联。
        """
        version_tag = kwargs.pop("version_tag", None)
        req = kwargs.pop("route", None)
        if req is None:
            req = RouteRequest(
                messages=messages,
                strategy=kwargs.pop("strategy", "balanced"),
                need_caps=set(kwargs.pop("need_caps", set())),
                max_cost_per_1k=kwargs.pop("max_cost_per_1k", None),
                max_latency_ms=kwargs.pop("max_latency_ms", None),
                est_context=kwargs.pop("est_context", 0),
            )
        provider, decision = self.route(req)
        resp = provider.chat(messages, **kwargs)
        usage = dict(resp.get("usage") or {})
        usage["routing"] = {
            "chosen": decision.chosen,
            "strategy": decision.strategy,
            "score": decision.score,
            "candidates": decision.candidates,
            "rejected": decision.rejected,
        }
        if version_tag is not None:
            usage["version_tag"] = version_tag   # 版本归因，不碰 prompt 内容
        resp["usage"] = usage
        resp["router"] = self.name
        return resp


def _norm(value: float, pool: list[float], invert: bool) -> float:
    """min-max 归一化到 [0,1]；invert=True 表示「越小越好」翻转。池内相等则记满分。"""
    lo, hi = min(pool), max(pool)
    if hi == lo:
        return 1.0
    x = (value - lo) / (hi - lo)
    return 1.0 - x if invert else x
