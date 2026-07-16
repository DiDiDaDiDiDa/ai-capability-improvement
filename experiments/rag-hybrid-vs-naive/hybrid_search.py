#!/usr/bin/env python3
"""
Hybrid Search 对照 Demo（L2）。
纯 Python 标准库：BM25 + hashed n-gram 向量 + RRF。

链路: Ingest → (Vector | BM25 | Hybrid/RRF) → hit@k 对比

运行: python3 hybrid_search.py
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------------------
# 0) 语料：在 L1 三份制度上，故意埋一个「稀有专名」便于对照
# ---------------------------------------------------------------------------

CORPUS: dict[str, str] = {
    "policy-travel.md": """
# 差旅报销制度

员工因公出差须事先提交差旅申请。交通优先高铁与经济舱。
住宿标准：一线城市每晚不超过 500 元，其他城市不超过 350 元。
餐饮补贴按天定额，超标自理。发票必须与行程单日期一致。
未经批准的超标住宿，财务有权拒报。
""".strip(),
    "hr-leave.md": """
# 休假与考勤

正式员工享有带薪年假，工龄不满 10 年者每年 5 天，满 10 年 10 天，满 20 年 15 天。
事假需直属领导审批；病假超过 3 天须提供医院证明。
调休优先消耗加班时长，不可预支。
""".strip(),
    "it-security.md": """
# 信息安全须知

生产环境密钥禁止写入代码仓库。访问客户数据须走工单并双人复核。
公共 Wi-Fi 下必须开启公司 VPN。发现钓鱼邮件立即上报安全组，勿点击附件。
机密系统令牌代号 X-KEY-99 仅限安全组轮换，禁止个人本地缓存。
""".strip(),
}


# ---------------------------------------------------------------------------
# 1) Chunk（与 L1 同构，便于对照）
# ---------------------------------------------------------------------------

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
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(
    doc_id: str,
    text: str,
    size: int = 70,
    overlap: int = 20,
) -> list[Chunk]:
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must satisfy 0 <= overlap < size")

    text = clean_text(text)
    if not text:
        return []

    step = size - overlap
    chunks: list[Chunk] = []
    start = 0
    idx = 0
    n = len(text)
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


# ---------------------------------------------------------------------------
# 2) 分词：英文/数字整词 + 汉字 bigram（教学用，无 jieba）
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|[a-zA-Z0-9]+|[一-鿿]+",
    re.UNICODE,
)


def tokenize(text: str) -> list[str]:
    """
    - 拉丁/数字串（含 X-KEY-99）整词保留，小写
    - 连续汉字切成 bigram（单字保留）
    """
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


# ---------------------------------------------------------------------------
# 3) Dense：hashed char n-gram（与 L1 同接口）
# ---------------------------------------------------------------------------

def _stable_hash(token: str, dim: int) -> int:
    h = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % dim


def embed_text(text: str, dim: int = 128, ngram: int = 2) -> list[float]:
    t = re.sub(r"\s+", "", text.lower())
    if not t:
        return [0.0] * dim
    vec = [0.0] * dim
    if len(t) < ngram:
        grams = [t]
    else:
        grams = [t[i : i + ngram] for i in range(len(t) - ngram + 1)]
    for g in grams:
        vec[_stable_hash(g, dim)] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# 4) BM25 索引
# ---------------------------------------------------------------------------

@dataclass
class BM25Index:
    k1: float = 1.5
    b: float = 0.75
    chunks: list[Chunk] = field(default_factory=list)
    doc_len: list[int] = field(default_factory=list)
    tf: list[Counter] = field(default_factory=list)
    df: Counter = field(default_factory=Counter)
    avgdl: float = 0.0
    n_docs: int = 0

    def add(self, chunks: Iterable[Chunk]) -> None:
        for ch in chunks:
            terms = tokenize(ch.text)
            c = Counter(terms)
            self.chunks.append(ch)
            self.doc_len.append(len(terms))
            self.tf.append(c)
            for t in c:
                self.df[t] += 1
        self.n_docs = len(self.chunks)
        self.avgdl = (
            sum(self.doc_len) / self.n_docs if self.n_docs else 0.0
        )

    def idf(self, term: str) -> float:
        # BM25+ 风格平滑 IDF，避免负值
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_idx: int) -> float:
        q_terms = tokenize(query)
        if not q_terms or self.avgdl <= 0:
            return 0.0
        dl = self.doc_len[doc_idx]
        tfs = self.tf[doc_idx]
        s = 0.0
        for t in q_terms:
            f = tfs.get(t, 0)
            if f <= 0:
                continue
            idf = self.idf(t)
            denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
            s += idf * (f * (self.k1 + 1.0)) / denom
        return s

    def search(self, query: str, top_k: int = 5) -> list[tuple[float, Chunk]]:
        scored = [
            (self.score(query, i), self.chunks[i])
            for i in range(self.n_docs)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        # 过滤零分，避免「全零乱序」伪装成命中
        scored = [x for x in scored if x[0] > 0]
        return scored[:top_k]


# ---------------------------------------------------------------------------
# 5) Vector store
# ---------------------------------------------------------------------------

@dataclass
class StoredChunk:
    chunk: Chunk
    vector: list[float]


@dataclass
class VectorStore:
    items: list[StoredChunk] = field(default_factory=list)

    def add(self, chunks: Iterable[Chunk]) -> None:
        for c in chunks:
            self.items.append(StoredChunk(chunk=c, vector=embed_text(c.text)))

    def search(self, query: str, top_k: int = 5) -> list[tuple[float, Chunk]]:
        qv = embed_text(query)
        scored = [(dot(qv, it.vector), it.chunk) for it in self.items]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
# 6) RRF 融合
# ---------------------------------------------------------------------------

def rrf_fuse(
    ranked_lists: list[list[tuple[float, Chunk]]],
    k: int = 60,
    top_k: int = 5,
) -> list[tuple[float, Chunk]]:
    """
    按 uid 融合多路排名。未出现在某路的文档不从该路加分。
    返回 (rrf_score, chunk) 降序。
    """
    scores: dict[str, float] = defaultdict(float)
    best_chunk: dict[str, Chunk] = {}
    for ranked in ranked_lists:
        for rank, (_raw, ch) in enumerate(ranked, start=1):
            uid = ch.uid
            scores[uid] += 1.0 / (k + rank)
            best_chunk[uid] = ch
    fused = [(scores[uid], best_chunk[uid]) for uid in scores]
    fused.sort(key=lambda x: x[0], reverse=True)
    return fused[:top_k]


def hybrid_search(
    query: str,
    vector_store: VectorStore,
    bm25: BM25Index,
    per_channel_k: int = 10,
    top_k: int = 5,
    rrf_k: int = 60,
) -> list[tuple[float, Chunk]]:
    dense = vector_store.search(query, top_k=per_channel_k)
    sparse = bm25.search(query, top_k=per_channel_k)
    return rrf_fuse([dense, sparse], k=rrf_k, top_k=top_k)


# ---------------------------------------------------------------------------
# 7) 评测
# ---------------------------------------------------------------------------

def hit_at_k(hits: list[tuple[float, Chunk]], gold_doc: str) -> bool:
    return any(ch.doc_id == gold_doc for _, ch in hits)


def top1_source(hits: list[tuple[float, Chunk]]) -> str:
    return hits[0][1].source if hits else "(empty)"


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def ingest(size: int = 70, overlap: int = 20) -> tuple[list[Chunk], VectorStore, BM25Index]:
    all_chunks: list[Chunk] = []
    for doc_id, raw in CORPUS.items():
        all_chunks.extend(chunk_text(doc_id, raw, size=size, overlap=overlap))
    vs = VectorStore()
    vs.add(all_chunks)
    bm = BM25Index()
    bm.add(all_chunks)
    print(f"  chunks={len(all_chunks)}  dense={len(vs.items)}  bm25_docs={bm.n_docs}")
    print(f"  avgdl={bm.avgdl:.1f}  vocab={len(bm.df)}")
    return all_chunks, vs, bm


def demo_tokenize() -> None:
    section("1) tokenize：专名整词 + 汉字 bigram")
    samples = [
        "X-KEY-99 禁止缓存",
        "一线城市住宿标准",
        "必须开启公司 VPN",
    ]
    for s in samples:
        print(f"  {s!r}")
        print(f"    → {tokenize(s)}")


def demo_channel_contrast(vs: VectorStore, bm: BM25Index) -> None:
    section("2) 三路对照：精确专名 vs 语义改写")
    cases = [
        # 稀有专名：稀疏应强
        ("X-KEY-99 能本地缓存吗？", "it-security.md", "exact_id"),
        # 字面 VPN
        ("公共 Wi-Fi 必须开 VPN 吗？", "it-security.md", "literal"),
        # 语义改写住宿
        ("去上海出差住酒店最多报多少钱？", "policy-travel.md", "paraphrase"),
        # 年假
        ("干了十二年带薪假几天？", "hr-leave.md", "paraphrase"),
    ]
    for q, gold, kind in cases:
        dense = vs.search(q, top_k=3)
        sparse = bm.search(q, top_k=3)
        hybrid = hybrid_search(q, vs, bm, per_channel_k=8, top_k=3)
        print(f"\nQ[{kind}]: {q}")
        print(f"  gold={gold}")
        for name, hits in ("vector", dense), ("bm25", sparse), ("hybrid", hybrid):
            ok = hit_at_k(hits, gold)
            heads = [
                f"{ch.source}:{score:.3f}" for score, ch in hits[:3]
            ]
            print(f"  {name:<6} hit@3={'YES' if ok else 'NO '} top={heads}")


def demo_rrf_breakdown(vs: VectorStore, bm: BM25Index) -> None:
    section("3) RRF 拆账：专名查询各 chunk 的 rank 贡献")
    q = "X-KEY-99 轮换规则"
    dense = vs.search(q, top_k=5)
    sparse = bm.search(q, top_k=5)
    print(f"Q: {q}")
    print("vector ranks:")
    for i, (s, ch) in enumerate(dense, 1):
        print(f"  r={i} score={s:.3f} {ch.source} | {ch.text[:36].replace(chr(10), ' ')}...")
    print("bm25 ranks:")
    for i, (s, ch) in enumerate(sparse, 1):
        print(f"  r={i} score={s:.3f} {ch.source} | {ch.text[:36].replace(chr(10), ' ')}...")

    # 手工展示 RRF 分
    k = 60
    contrib: dict[str, dict[str, float]] = defaultdict(lambda: {"vector": 0.0, "bm25": 0.0})
    chunks: dict[str, Chunk] = {}
    for rank, (_s, ch) in enumerate(dense, 1):
        contrib[ch.uid]["vector"] = 1.0 / (k + rank)
        chunks[ch.uid] = ch
    for rank, (_s, ch) in enumerate(sparse, 1):
        contrib[ch.uid]["bm25"] = 1.0 / (k + rank)
        chunks[ch.uid] = ch
    rows = []
    for uid, parts in contrib.items():
        total = parts["vector"] + parts["bm25"]
        rows.append((total, uid, parts["vector"], parts["bm25"]))
    rows.sort(reverse=True)
    print("RRF (k=60) top:")
    for total, uid, v, b in rows[:5]:
        print(f"  {uid:<22} rrf={total:.5f}  from_v={v:.5f} from_b={b:.5f}")

    fused = rrf_fuse([dense, sparse], k=60, top_k=3)
    assert hit_at_k(fused, "it-security.md"), "hybrid must surface IT doc for X-KEY-99"
    print(f"  hybrid top1 → {top1_source(fused)} (assert gold IT)")


def demo_hit_table(vs: VectorStore, bm: BM25Index) -> None:
    section("4) 小金标 hit@3 汇总（教学语料）")
    gold_set = [
        ("X-KEY-99 禁止个人缓存", "it-security.md"),
        ("一线城市住宿上限", "policy-travel.md"),
        ("工龄满十年年假天数", "hr-leave.md"),
        ("钓鱼邮件怎么处理", "it-security.md"),
        ("超标住宿财务能否拒报", "policy-travel.md"),
        ("病假三天以上要什么证明", "hr-leave.md"),
        # 强改写：字面几乎不重合，暴露纯向量 n-gram 脆弱点
        ("干了十二年带薪假几天？", "hr-leave.md"),
    ]
    stats = {"vector": 0, "bm25": 0, "hybrid": 0}
    n = len(gold_set)
    for q, gold in gold_set:
        v_ok = hit_at_k(vs.search(q, top_k=3), gold)
        b_ok = hit_at_k(bm.search(q, top_k=3), gold)
        h_ok = hit_at_k(hybrid_search(q, vs, bm, per_channel_k=8, top_k=3), gold)
        stats["vector"] += int(v_ok)
        stats["bm25"] += int(b_ok)
        stats["hybrid"] += int(h_ok)
        flag = (
            f"v={'Y' if v_ok else 'n'} "
            f"b={'Y' if b_ok else 'n'} "
            f"h={'Y' if h_ok else 'n'}"
        )
        print(f"  [{flag}] {q} → {gold}")

    print("\n  hit@3 rate:")
    for name in ("vector", "bm25", "hybrid"):
        rate = stats[name] / n
        bar = "█" * stats[name] + "░" * (n - stats[name])
        print(f"    {name:<6} {bar} {stats[name]}/{n} ({rate:.0%})")

    # Hybrid 应至少不弱于较差的那一路；教学语料上通常 ≥ max(单路)
    assert stats["hybrid"] >= min(stats["vector"], stats["bm25"]), (
        "hybrid should not be worse than both singles on this set"
    )
    # 专名题：BM25 或 Hybrid 必须中
    assert hit_at_k(
        hybrid_search("X-KEY-99 禁止个人缓存", vs, bm, per_channel_k=8, top_k=3),
        "it-security.md",
    )


def demo_naive_vs_hybrid_story(vs: VectorStore, bm: BM25Index) -> None:
    section("5) 故事线：Naive 漏召回 → Hybrid 捞回")
    # 专名：BM25 一锤定音；改写：BM25 bigram 仍可比纯 n-gram 向量稳
    cases = [
        ("令牌代号 X-KEY-99 能否写进个人笔记？", "it-security.md", "exact_id"),
        ("干了十二年带薪假几天？", "hr-leave.md", "paraphrase"),
    ]
    recovered = 0
    for q, gold, kind in cases:
        dense = vs.search(q, top_k=3)
        hybrid = hybrid_search(q, vs, bm, per_channel_k=10, top_k=3)
        v_hit = hit_at_k(dense, gold)
        h_hit = hit_at_k(hybrid, gold)
        print(f"\nQ[{kind}]: {q}")
        print("  Naive(vector) top:")
        for s, ch in dense:
            mark = "← gold" if ch.doc_id == gold else ""
            print(f"    {s:.3f} {ch.source} {mark}")
        print("  Hybrid(RRF) top:")
        for s, ch in hybrid:
            mark = "← gold" if ch.doc_id == gold else ""
            print(f"    {s:.5f} {ch.source} {mark}")
        print(f"  vector_hit={v_hit}  hybrid_hit={h_hit}")
        assert h_hit, f"hybrid must hit gold for {kind}"
        if h_hit and not v_hit:
            recovered += 1
            print("  → [对比成立] 纯向量 miss，Hybrid 靠 BM25 通道捞回")
        elif h_hit and v_hit:
            print("  → 两路都能中；RRF 用于稳住 rank，不靠单通道赌命")
    assert recovered >= 1, "need at least one case where hybrid recovers vector miss"
    print(f"\n  recovered_from_vector_miss={recovered}")


def main() -> None:
    print("Hybrid Search L2 demo (stdlib only: BM25 + vector + RRF)")
    demo_tokenize()
    section("Ingest corpus")
    _chunks, vs, bm = ingest()
    demo_channel_contrast(vs, bm)
    demo_rrf_breakdown(vs, bm)
    demo_hit_table(vs, bm)
    demo_naive_vs_hybrid_story(vs, bm)
    section("DONE · L2 hybrid green")
    print("pipeline: chunk → dense∥bm25 → RRF → hit@k ≥ single-channel baseline")


if __name__ == "__main__":
    main()
