"""P2 · AI Gateway 增强版 —— Model Router（复用 P1 LLMProvider 契约）。"""

from .providers import ModelProfile, ScriptedProvider
from .router import ModelRouter, RouteRequest, RouteError
from .semantic_cache import CachedProvider, SemanticCache, cosine, embed_text
from .prompt_client import (
    PromptClient,
    PromptRegistry,
    PromptRequest,
    PromptSpec,
    RegistryError,
    Template,
)

__all__ = [
    "ModelProfile",
    "ScriptedProvider",
    "ModelRouter",
    "RouteRequest",
    "RouteError",
    "SemanticCache",
    "CachedProvider",
    "embed_text",
    "cosine",
    "PromptClient",
    "PromptRegistry",
    "PromptRequest",
    "PromptSpec",
    "RegistryError",
    "Template",
]
