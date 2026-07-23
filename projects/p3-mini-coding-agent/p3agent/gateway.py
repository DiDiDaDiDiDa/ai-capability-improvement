"""
M5 · Gateway 接缝 —— 证明「policy 里的 LLM 可热替换」，对接模块 06 / 项目 P2。

回到前面钉死的边界：模型只生成 {action, action_input}（决策），宿主执行工具并回填
Observation。所以「换模型」= 换一个能产出 Step 的 provider，loop 和工具层都不用动。

这里定义 LLMProvider 抽象 + 一个 Mock 实现（把已验证的 policy_fix_add 包一层），
证明接缝存在。生产上换成 OpenAIProvider / AnthropicProvider（走 P2 Gateway 的
Router / Fallback / Cost），policy 函数签名不变。
"""
from __future__ import annotations

from typing import Protocol

from .loop import Step
from .policy import policy_fix_add
from .tools import TOOL_REGISTRY, Workspace


class LLMProvider(Protocol):
    """决策器抽象：给任务+历史+可用工具，产出下一步 Step。"""

    name: str

    def decide(self, task: str, history: list[Step], ws: Workspace) -> Step: ...


class MockProvider:
    """离线教学 provider：复用已验证的 policy，证明接缝可插拔。"""

    name = "mock"

    def decide(self, task: str, history: list[Step], ws: Workspace) -> Step:
        return policy_fix_add(task, history, ws)


class GatewayPolicy:
    """把 provider 适配成 loop 认识的 PolicyFn(task, history, ws) -> Step。

    额外职责（Gateway 的一等公民）：把当前工具表的 schema 作为「可用工具清单」
    暴露给 provider —— 真实 LLM 的 function-calling 就吃这个。
    """

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def available_tools(self) -> list[dict]:
        return [spec.schema() for spec in TOOL_REGISTRY.values()]

    def __call__(self, task: str, history: list[Step], ws: Workspace) -> Step:
        # 生产：此处把 available_tools() 传给 provider 做 function-calling。
        # 教学：mock 直接按已验证策略决策。
        return self.provider.decide(task, history, ws)


def build_gateway_policy(provider: LLMProvider | None = None) -> GatewayPolicy:
    """默认用 MockProvider；换 provider 即换模型，loop/工具零改动。"""
    return GatewayPolicy(provider or MockProvider())
