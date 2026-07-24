"""
Semantic Cache（P2 M3）—— 语义相似命中，省调用。

底层逻辑：普通 cache 按 key 精确匹配（问法变一个字就 miss）；语义 cache 把 query
嵌成向量，与缓存里的向量算余弦相似度，**相似度 ≥ 阈值就复用旧答案**，省掉一次 LLM 调用。

关键权衡（阈值是灵魂）：
  阈值高 → 命中率低，但安全（几乎一样才命中）
  阈值低 → 命中率高，但危险（不同意图被误判为相似 → 返回错答案）

embedding 用 hashing + n-gram（与 P1 `embed_text` 同源思路，教学自包含）；生产替换为
sentence-transformers / OpenAI embedding + 向量库（Redis/FAISS），方法不变。
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable


def embed_text(text: str, dim: int = 128, ngram: int = 2) -> list[float]:
    """字符 n-gram 哈希到定长向量并归一化（与 P1 retrieve.embed_text 同源）。"""
    t = re.sub(r"\s+", "", text.lower())
    if not t:
        return [0.0] * dim
    vec = [0.0] * dim
    grams = [t] if len(t) < ngram else [t[i : i + ngram] for i in range(len(t) - ngram + 1)]
    for g in grams:
        idx = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:8], 16) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """归一化向量的点积即余弦相似度。"""
    return sum(x * y for x, y in zip(a, b))


@dataclass
class CacheEntry:
    key_text: str
    vec: list[float]
    value: dict[str, Any]
    created_at: float


@dataclass
class SemanticCache:
    """
    语义缓存核心：嵌入 query → 找最相似条目 → ≥阈值命中。

    参数：
      threshold  余弦相似度命中门槛（默认 0.9，偏保守防误命中）
      ttl_s      条目存活秒数（None 不过期）；过期条目命中时视为 miss 并清除
      max_size   容量上限，超出淘汰最旧条目（FIFO；生产可换 LRU）
    """

    threshold: float = 0.9
    ttl_s: float | None = None
    max_size: int = 256
    entries: list[CacheEntry] = field(default_factory=list)
    hits: int = 0
    misses: int = 0

    def _expired(self, e: CacheEntry, now: float) -> bool:
        return self.ttl_s is not None and (now - e.created_at) > self.ttl_s

    def get(self, query: str) -> tuple[dict[str, Any] | None, float, str | None]:
        """返回 (命中值 or None, 最高相似度, 命中的 key_text)。顺带清理过期条目。"""
        now = time.time()
        self.entries = [e for e in self.entries if not self._expired(e, now)]
        if not self.entries:
            self.misses += 1
            return None, 0.0, None
        qv = embed_text(query)
        best, best_sim = None, -1.0
        for e in self.entries:
            sim = cosine(qv, e.vec)
            if sim > best_sim:
                best, best_sim = e, sim
        if best is not None and best_sim >= self.threshold:
            self.hits += 1
            return best.value, best_sim, best.key_text
        self.misses += 1
        return None, max(best_sim, 0.0), None

    def put(self, query: str, value: dict[str, Any]) -> None:
        self.entries.append(CacheEntry(query, embed_text(query), value, time.time()))
        if len(self.entries) > self.max_size:
            self.entries.pop(0)  # FIFO 淘汰最旧

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
            "size": len(self.entries),
        }


def _cache_key(messages: list[dict[str, str]]) -> str:
    """用最后一条 user 消息做缓存键（语义命中只看当前问法）。"""
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


@dataclass
class CachedProvider:
    """
    缓存装饰器：实现 LLMProvider.chat 契约，套在任意 Provider（含 ModelRouter）外层。
      命中 → 直接返回旧答案，标 cache=hit，省掉底层调用
      未命中 → 委托底层执行，写回缓存，标 cache=miss

    组合方向（重要）：Cache 应在 Router *之外*——先查缓存，命中就连模型都不用选。
    """

    inner: Any                                   # 底层 LLMProvider（Router / Provider）
    cache: SemanticCache = field(default_factory=SemanticCache)
    name: str = "semantic-cache"

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        # version_tag：应用层 SDK 传下来的不透明版本标签，仅归因，不解析 prompt
        version_tag = kwargs.pop("version_tag", None)
        query = _cache_key(messages)
        cached, sim, matched = self.cache.get(query)
        if cached is not None:
            resp = dict(cached)                  # 拷贝，避免调用方改到缓存内容
            usage = dict(resp.get("usage") or {})
            usage["cache"] = {"status": "hit", "similarity": round(sim, 4),
                              "matched_query": matched, "saved_call": True}
            if version_tag is not None:
                usage["version_tag"] = version_tag   # 命中也记当前请求的版本
            resp["usage"] = usage
            return resp
        resp = self.inner.chat(messages, **kwargs)
        self.cache.put(query, resp)
        usage = dict(resp.get("usage") or {})
        usage["cache"] = {"status": "miss", "similarity": round(sim, 4), "saved_call": False}
        if version_tag is not None:
            usage["version_tag"] = version_tag
        resp["usage"] = usage
        return resp
