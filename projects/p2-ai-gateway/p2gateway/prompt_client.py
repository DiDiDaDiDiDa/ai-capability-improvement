"""
Prompt Version 管理（应用层 SDK · 复用模块 02）—— 不属于 Gateway，属于业务/应用层。

分层定位（重要，见 prompt-version.md）：
  应用层 SDK（本文件）：id+变量 → 解析版本 → 渲染 messages。渲染要用业务变量，是业务语义。
  Gateway（router/cache）：只吃「已渲染 messages + 不透明 version_tag」，做选型/缓存/归因，
                           永不碰 prompt_id / 变量 / 模板 —— 保持 prompt-agnostic。

职责边界：
  SDK 侧 → resp["prompt_meta"]  写完整版本信息（template_id/version/fingerprint/resolved_by）
  Gateway 侧 → usage["version_tag"]  只标一个不透明字符串 "qa@v1"，用于把版本与成本/延迟关联

直接 import 模块 02 的 PromptRegistry（experiments/prompt-sdk），一行没重写。
"""
from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any, Sequence

# --- 复用模块 02：把 prompt-sdk 目录挂上 sys.path 后 import 真实实现 ---
_REPO = pathlib.Path(__file__).resolve().parents[3]
_SDK = _REPO / "experiments" / "prompt-sdk"
if str(_SDK) not in sys.path:
    sys.path.insert(0, str(_SDK))

from prompt_registry import (  # noqa: E402  (path bootstrap must come first)
    PromptRegistry,
    PromptSpec,
    RegistryError,
    Template,
)

__all__ = [
    "PromptRegistry",
    "PromptSpec",
    "Template",
    "RegistryError",
    "PromptRequest",
    "PromptClient",
]


@dataclass
class PromptRequest:
    """一次带版本治理的调用意图（业务侧只有 id + 变量 + 版本选择，不碰 prompt 字符串）。"""

    prompt_id: str
    variables: dict[str, Any] = field(default_factory=dict)
    version: str | None = None                   # 钉扎精确版本（可复现）
    alias: str | None = None                     # 走别名（prod/canary，发布回滚只动 alias）
    ab: Sequence[tuple[str, int]] | None = None  # A/B: [(version, weight), ...]
    user_key: str = "anon"                       # A/B 稳定分桶键
    experiment_id: str = "default"


@dataclass
class PromptClient:
    """
    应用层 SDK：resolve → render messages → 调用 gateway（下游 LLMProvider）。

    与 Gateway 的边界：SDK 把 prompt 渲染成 messages，并算出一个不透明 version_tag
    透传给 gateway 做归因；gateway 只见 messages + tag，不见 prompt_id/变量/模板。
    """

    registry: PromptRegistry
    gateway: Any                                 # 下游 LLMProvider（CachedProvider/Router/...）
    name: str = "prompt-client"

    def resolve_spec(self, req: PromptRequest) -> tuple[PromptSpec, dict[str, Any]]:
        """按 ab > version/alias > latest 解析出唯一版本，返回 spec + 解析元数据。"""
        if req.ab:
            spec, exp = self.registry.ab_route(
                req.prompt_id, req.user_key, req.ab, experiment_id=req.experiment_id
            )
            return spec, {"resolved_by": "ab", **exp}
        spec = self.registry.resolve(req.prompt_id, version=req.version, alias=req.alias)
        by = "version" if req.version else ("alias" if req.alias else "latest")
        return spec, {"resolved_by": by, "alias": req.alias}

    def run(self, req: PromptRequest, **chat_kwargs: Any) -> dict[str, Any]:
        """端到端：定版本 → 渲染 messages → 传 version_tag 调 gateway → 附 SDK 侧版本记录。"""
        spec, ver_meta = self.resolve_spec(req)
        messages = spec.build(**req.variables)   # 缺变量在此早失败（模块 02 契约）
        version_tag = f"{spec.template_id}@{spec.version}"

        # 把不透明 tag 透传给 gateway：有 gateway 组件会 stamp 进 usage.version_tag
        resp = self.gateway.chat(messages, version_tag=version_tag, **chat_kwargs)

        # 应用层记录：完整版本信息放 prompt_meta（与 gateway 的不透明 tag 分离）
        resp["prompt_meta"] = {
            "template_id": spec.template_id,
            "version": spec.version,
            "version_tag": version_tag,
            "fingerprint": spec.content_fingerprint()[:12],
            **ver_meta,
        }
        # 若下游是纯 provider（无 gateway 组件）没 stamp，SDK 兜底补 tag，保证归因不丢
        usage = dict(resp.get("usage") or {})
        usage.setdefault("version_tag", version_tag)
        resp["usage"] = usage
        resp["messages"] = messages              # 便于验收核对渲染结果
        return resp
