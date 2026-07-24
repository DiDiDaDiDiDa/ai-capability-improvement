"""
Provider 抽象 + 元数据（P2 M1 地基，兼容 P1 LLMProvider 契约）。

契约对齐 P1：chat(messages, **kwargs) -> {content, usage, provider}
额外给每个 Provider 挂一份 ModelProfile（成本/延迟/能力/质量），Router 靠它选型。
真实场景：profile 来自各家定价页 + 线上延迟监控；这里用可复现的脚本值教学。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelProfile:
    """选型所需的模型画像。cost 单位：美元/1K token（in+out 合计的粗略均价）。"""

    name: str
    cost_per_1k: float          # 越低越便宜
    latency_ms: float           # 典型端到端延迟，越低越快
    quality: float              # 0~1 相对质量分（越高越强）
    capabilities: frozenset[str] = field(default_factory=frozenset)  # 如 {"code","vision","zh"}
    max_context: int = 8192

    def supports(self, needed: set[str]) -> bool:
        return needed.issubset(self.capabilities)


@dataclass
class ScriptedProvider:
    """
    教学 Provider：不调网络，按 profile 生成可复现响应 + usage。
    生产替换为 P1 的 HttpGatewayProvider（同 chat 契约），Router 无感。
    """

    profile: ModelProfile
    healthy: bool = True         # 供 Fallback/熔断演示（本次先留位）

    @property
    def name(self) -> str:
        return self.profile.name

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        if not self.healthy:
            raise RuntimeError(f"provider unhealthy: {self.name}")
        user = ""
        for m in messages:
            if m.get("role") == "user":
                user = m.get("content", "")
        prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        content = f"[{self.name}] answer: {user[:60]}"
        completion_tokens = len(content) // 4
        return {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": round(
                    (prompt_tokens + completion_tokens) / 1000 * self.profile.cost_per_1k, 6
                ),
                "latency_ms": self.profile.latency_ms,
            },
            "provider": self.name,
        }
