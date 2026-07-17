"""Hybrid 检索（BM25 + Vector + RRF）— 与模块 03 L2 同构，可热替换。"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|[一-鿿]+", re.UNICODE)


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: int
    text: str
    start: int
    end: int

    @property
    def source(self) -> str:
        return f"{self.doc_id}#{self.chunk_id}"

    @property
    def uid(self) -> str:
        return self.source


def clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_text(doc_id: str, text: str, size: int = 70, overlap: int = 20) -> list[Chunk]:
    if size <= 0 or not (0 <= overlap < size):
        raise ValueError("bad size/overlap")
    text = clean_text(text)
    if not text:
        return []
    step = size - overlap
    chunks: list[Chunk] = []
    start, idx, n = 0, 0, len(text)
    while start < n:
        end = min(start + size, n)
        piece = text[start:end].strip()
        if piece:
            chunks.append(Chunk(doc_id, idx, piece, start, end))
            idx += 1
        if end >= n:
            break
        start += step
    return chunks


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        piece = m.group(0)
        if re.fullmatch(r"[一-鿿]+", piece):
            if len(piece) == 1:
                tokens.append(piece)
            else:
                tokens.extend(piece[i : i + 2] for i in range(len(piece) - 1))
        else:
            tokens.append(piece.lower())
    return tokens


def embed_text(text: str, dim: int = 128, ngram: int = 2) -> list[float]:
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


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass
class HybridIndex:
    chunks: list[Chunk] = field(default_factory=list)
    vecs: list[list[float]] = field(default_factory=list)
    tf: list[Counter] = field(default_factory=list)
    doc_len: list[int] = field(default_factory=list)
    df: Counter = field(default_factory=Counter)
    avgdl: float = 0.0
    k1: float = 1.5
    b: float = 0.75

    def build(self, corpus: dict[str, str], size: int = 70, overlap: int = 20) -> None:
        self.chunks.clear()
        self.vecs.clear()
        self.tf.clear()
        self.doc_len.clear()
        self.df = Counter()
        for doc_id, raw in corpus.items():
            for ch in chunk_text(doc_id, raw, size=size, overlap=overlap):
                self.chunks.append(ch)
                self.vecs.append(embed_text(ch.text))
                terms = tokenize(ch.text)
                c = Counter(terms)
                self.tf.append(c)
                self.doc_len.append(len(terms))
                for t in c:
                    self.df[t] += 1
        n = len(self.chunks)
        self.avgdl = sum(self.doc_len) / n if n else 0.0

    def _bm25(self, query: str, i: int) -> float:
        q_terms = tokenize(query)
        if not q_terms or self.avgdl <= 0:
            return 0.0
        n, dl, tfs, s = len(self.chunks), self.doc_len[i], self.tf[i], 0.0
        for t in q_terms:
            f = tfs.get(t, 0)
            if f <= 0:
                continue
            idf = math.log(1.0 + (n - self.df.get(t, 0) + 0.5) / (self.df.get(t, 0) + 0.5))
            denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
            s += idf * (f * (self.k1 + 1.0)) / denom
        return s

    def search(self, query: str, top_k: int = 3) -> list[tuple[float, Chunk]]:
        n = len(self.chunks)
        if n == 0:
            return []
        qv = embed_text(query)
        vec_rank = sorted(range(n), key=lambda i: dot(qv, self.vecs[i]), reverse=True)
        bm_scored = [(self._bm25(query, i), i) for i in range(n)]
        bm_rank = [i for s, i in sorted(bm_scored, key=lambda x: x[0], reverse=True) if s > 0]
        rrf: dict[int, float] = {}
        for rank, i in enumerate(vec_rank, start=1):
            rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank)
        for rank, i in enumerate(bm_rank, start=1):
            rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank)
        fused = sorted(rrf.items(), key=lambda x: (-x[1], self.chunks[x[0]].uid))
        return [(score, self.chunks[i]) for i, score in fused[:top_k]]
