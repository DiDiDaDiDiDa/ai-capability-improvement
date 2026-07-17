"""端到端 RAG Pipeline：ingest → hybrid retrieve → grounded prompt → gateway。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .gateway import LLMProvider, MockGatewayProvider, make_provider
from .ingest import load_corpus
from .prompt import build_messages, validate_grounded_payload
from .retrieve import Chunk, HybridIndex


@dataclass
class AskResult:
    question: str
    answer: str
    citations: list[dict[str, Any]]
    hits: list[dict[str, Any]]
    provider: str
    usage: dict[str, Any]
    prompt_meta: dict[str, str]
    grounded_ok: bool
    gold_hit: bool | None = None


@dataclass
class RAGPipeline:
    index: HybridIndex = field(default_factory=HybridIndex)
    provider: LLMProvider = field(default_factory=MockGatewayProvider)
    corpus: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_data_dir(
        cls,
        data_dir: Path | str,
        provider: LLMProvider | None = None,
        provider_kind: str | None = None,
    ) -> "RAGPipeline":
        corpus = load_corpus(data_dir)
        index = HybridIndex()
        index.build(corpus)
        prov = provider or make_provider(provider_kind)
        return cls(index=index, provider=prov, corpus=corpus)

    def retrieve(self, question: str, top_k: int = 3) -> list[tuple[float, Chunk]]:
        return self.index.search(question, top_k=top_k)

    def ask(self, question: str, top_k: int = 3, gold_doc: str | None = None) -> AskResult:
        hits = self.retrieve(question, top_k=top_k)
        payload = build_messages(question, hits)
        errs = validate_grounded_payload(payload)
        resp = self.provider.chat(payload["messages"])
        gold_hit = None
        if gold_doc is not None:
            gold_hit = any(ch.doc_id == gold_doc for _s, ch in hits)
        return AskResult(
            question=question,
            answer=resp["content"],
            citations=list(payload["citations"]),
            hits=[
                {"score": round(s, 4), "source": ch.source, "preview": ch.text[:80]}
                for s, ch in hits
            ],
            provider=str(resp.get("provider", getattr(self.provider, "name", "?"))),
            usage=dict(resp.get("usage") or {}),
            prompt_meta={
                "template_id": payload["template_id"],
                "version": payload["version"],
                "grounded_errors": ",".join(errs) if errs else "",
            },
            grounded_ok=not errs,
            gold_hit=gold_hit,
        )
