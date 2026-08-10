"""P2 · AI Gateway 增强版 —— Model Router（复用 P1 LLMProvider 契约）。"""

from .cost_dashboard import (
    CostTracker,
    MeteredProvider,
    UsageRecord,
    record_from_usage,
    render_dashboard,
)
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
from .resilience import (
    AllProvidersFailed,
    FatalError,
    ResilientProvider,
    RetryableError,
)
from .circuit_breaker import BreakerRegistry, CircuitBreaker
from .guardrail import GuardedProvider, GuardResult, mask_text
from .rate_limit import (
    Quota,
    QuotaExceeded,
    RateLimitedProvider,
    RateLimitExceeded,
    TokenBucket,
)
from .observability import MetricsRegistry, Span, TracedProvider

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
    "UsageRecord",
    "CostTracker",
    "MeteredProvider",
    "record_from_usage",
    "render_dashboard",
    "ResilientProvider",
    "RetryableError",
    "FatalError",
    "AllProvidersFailed",
    "CircuitBreaker",
    "BreakerRegistry",
    "GuardedProvider",
    "GuardResult",
    "mask_text",
    "RateLimitedProvider",
    "RateLimitExceeded",
    "QuotaExceeded",
    "TokenBucket",
    "Quota",
    "TracedProvider",
    "MetricsRegistry",
    "Span",
]
