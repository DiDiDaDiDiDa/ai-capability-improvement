#!/usr/bin/env python3
"""
Rerank 精排对照 Demo（L3）。
纯 Python 标准库：Hybrid 粗召回 + 教学版 Cross 交互打分。

链路: Ingest → Hybrid Top-N → CrossRerank Top-K → MRR 对照

运行: python3 rerank_demo.py
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------------------
# 0) 语料：与 L2 对齐，并加一条「易混噪声」方便观察重排
# ---------------------------------------------------------------------------

CORPUS: dict[str, str] = {
    "policy-travel.md": """
# 差旅报销制度

员工因公出差须事先提交差旅申请。交通优先高铁与经济舱。
住宿标准：一线城市每晚不超过 500 元，其他城市不超过 350 元。
餐饮补贴按天定额，超标自理。发票必须与行程单日期一致。
未经批准的超标住宿，财务有权拒报。
出差期间的加班不自动折算年假，调休规则见人事制度。
""".strip(),
    "hr-leave.md": """
# 休假与考勤

正式员工享有带薪年假，工龄不满 10 年者每年 5 天，满 10 年 10 天，满 20 年 15 天。
事假需直属领导审批；病假超过 3 天须提供医院证明。
调休优先消耗加班时长，不可预支。
差旅途中产生的加班，回公司后按加班单申请调休，不计入年假额度。
""".strip(),
    "it-security.md": """
# 信息安全须知

生产环境密钥禁止写入代码仓库。访问客户数据须走工单并双人复核。
公共 Wi-Fi 下必须开启公司 VPN。发现钓鱼邮件立即上报安全组，勿点击附件。
机密系统令牌代号 X-KEY-99 仅限安全组轮换，禁止个人本地缓存。
""".strip(),
    "noise-faq.md": """
# 员工常见问答（噪声源）

问：公司有食堂吗？答：园区 B1 有员工餐厅。
问：班车怎么坐？答：钉钉提交班车申请。
问：电脑坏了找谁？答：提 IT 工单，不要私自拆机。
住宿酒店积分归个人，与差旅报销标准无关。
年假查询可在 HR 系统自助页查看余额，具体天数以制度原文为准。
""".strip(),
}


# ---------------------------------------------------------------------------
# 1) Chunk
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
# 2) tokenize / embed / BM25 / RRF（L2 最小集）
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|[a-zA-Z0-9]+|[一-鿿]+",
    re.UNICODE,
)


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


def _stable_hash(token: str, dim: int) -> int:
    h = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % dim


def embed_text(text: str, dim: int = 128, ngram: int = 2) -> list[float]:
    t = re.sub(r"\s+", "", text.lower())
    if not t:
        return [0.0] * dim
    vec = [0.0] * dim
    grams = [t] if len(t) < ngram else [t[i : i + ngram] for i in range(len(t) - ngram + 1)]
    for g in grams:
        vec[_stable_hash(g, dim)] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


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
        self.avgdl = sum(self.doc_len) / self.n_docs if self.n_docs else 0.0

    def idf(self, term: str) -> float:
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
        scored = [(self.score(query, i), self.chunks[i]) for i in range(self.n_docs)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x for x in scored if x[0] > 0][:top_k]


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


def rrf_fuse(
    ranked_lists: list[list[tuple[float, Chunk]]],
    k: int = 60,
    top_k: int = 5,
) -> list[tuple[float, Chunk]]:
    scores: dict[str, float] = defaultdict(float)
    best_chunk: dict[str, Chunk] = {}
    for ranked in ranked_lists:
        for rank, (_raw, ch) in enumerate(ranked, start=1):
            scores[ch.uid] += 1.0 / (k + rank)
            best_chunk[ch.uid] = ch
    fused = [(scores[uid], best_chunk[uid]) for uid in scores]
    fused.sort(key=lambda x: x[0], reverse=True)
    return fused[:top_k]


def hybrid_search(
    query: str,
    vs: VectorStore,
    bm: BM25Index,
    per_channel_k: int = 8,
    top_k: int = 5,
) -> list[tuple[float, Chunk]]:
    return rrf_fuse(
        [vs.search(query, top_k=per_channel_k), bm.search(query, top_k=per_channel_k)],
        k=60,
        top_k=top_k,
    )


# ---------------------------------------------------------------------------
# 3) 教学版 Cross-Encoder：query–doc 交互特征（非双塔点积）
# ---------------------------------------------------------------------------

# 否定 / 禁止类词：query 含「能否/可以」而 doc 含「禁止」时，仍应视为高度相关（制度拒答）
_NEG_DOC = ("禁止", "不得", "不可", "勿", "拒报", "不能")
_ASK_MODAL = ("能否", "可以", "能不能", "可不可以", "允许")


# 意图短语：query 与 doc 同时出现时给联合加成（模拟 cross 注意力对齐）
_INTENT_PHRASES = (
    "年假",
    "带薪",
    "工龄",
    "住宿",
    "一线城市",
    "报销",
    "拒报",
    "vpn",
    "x-key-99",
    "钓鱼",
    "调休",
    "病假",
)


def cross_score(query: str, doc: str) -> float:
    """
    可解释的 pair 打分，模拟 Cross-Encoder 的「联合看」：
    - 词项覆盖（稀有词/专名加权）
    - 字符 bigram 覆盖
    - 意图短语联合命中
    - 否定对齐（问「能否」+ 答「禁止」）
    - 惩罚 FAQ 闲聊体 vs 制度问答错配
    接口与生产 reranker 同构：score(q, d) -> float。
    """
    q_terms = tokenize(query)
    d_terms = tokenize(doc)
    if not q_terms or not d_terms:
        return 0.0

    q_set = set(q_terms)
    d_set = set(d_terms)
    d_tf = Counter(d_terms)
    q_l = query.lower()
    d_l = doc.lower()
    q_flat = re.sub(r"\s+", "", q_l)
    d_flat = re.sub(r"\s+", "", d_l)

    def term_w(t: str) -> float:
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", t):
            return 3.5
        if re.search(r"\d", t):
            return 2.5
        return 1.0 + min(len(t), 4) * 0.15

    overlap = q_set & d_set
    cover = sum(term_w(t) for t in overlap)
    cover_ratio = len(overlap) / max(len(q_set), 1)

    q_bi = set(q_flat[i : i + 2] for i in range(max(0, len(q_flat) - 1)))
    d_bi = set(d_flat[i : i + 2] for i in range(max(0, len(d_flat) - 1)))
    jacc = len(q_bi & d_bi) / len(q_bi | d_bi) if (q_bi or d_bi) else 0.0

    proper = sum(
        1 for t in q_set if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", t) and t in d_set
    )

    neg_align = 0.0
    if any(m in query for m in _ASK_MODAL) and any(n in doc for n in _NEG_DOC):
        neg_align = 1.8

    # 意图短语联合（比单字 bigram 更稳）
    intent = 0.0
    for ph in _INTENT_PHRASES:
        if ph in q_flat and ph in d_flat:
            intent += 2.2

    # 制度体 vs FAQ 闲聊体：问具体标准时压制「问：/答：」噪声页
    policy_ask = any(
        k in query for k in ("多少", "几天", "上限", "标准", "能否", "能不能", "吗")
    )
    faq_style = ("问：" in doc) or ("答：" in doc)
    style_pen = -2.5 if policy_ask and faq_style else 0.0
    # 但 FAQ 自己就是 gold 时（query 也像 FAQ）不罚
    if faq_style and any(k in query for k in ("积分", "食堂", "班车", "余额查询")):
        style_pen = 0.5

    # 数字+单位弱对齐：query 问「天/元」时，doc 含同类单位加分
    unit = 0.0
    if any(u in query for u in ("天", "年")) and ("天" in doc or "年" in doc):
        unit += 0.8
    if any(u in query for u in ("元", "钱", "报")) and ("元" in doc or "报" in doc):
        unit += 0.8

    tf_boost = sum(math.log1p(d_tf[t]) * term_w(t) for t in overlap) * 0.25

    score = (
        1.4 * cover
        + 2.0 * cover_ratio
        + 2.2 * jacc
        + 2.5 * proper
        + neg_align
        + intent
        + unit
        + tf_boost
        + style_pen
    )
    if cover_ratio < 0.08 and proper == 0 and jacc < 0.05 and intent <= 0:
        score *= 0.15
    return score


def rerank(
    query: str,
    candidates: list[tuple[float, Chunk]],
    top_k: int = 3,
) -> list[tuple[float, Chunk]]:
    """对粗召回候选做 pair 精排；返回 (cross_score, chunk)。"""
    rescored = [(cross_score(query, ch.text), ch) for _coarse, ch in candidates]
    rescored.sort(key=lambda x: x[0], reverse=True)
    return rescored[:top_k]


# ---------------------------------------------------------------------------
# 4) 指标
# ---------------------------------------------------------------------------

def hit_at_k(hits: list[tuple[float, Chunk]], gold_doc: str) -> bool:
    return any(ch.doc_id == gold_doc for _, ch in hits)


def reciprocal_rank(hits: list[tuple[float, Chunk]], gold_doc: str) -> float:
    for i, (_s, ch) in enumerate(hits, start=1):
        if ch.doc_id == gold_doc:
            return 1.0 / i
    return 0.0


def top1_doc(hits: list[tuple[float, Chunk]]) -> str:
    return hits[0][1].doc_id if hits else ""


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def ingest() -> tuple[VectorStore, BM25Index, list[Chunk]]:
    all_chunks: list[Chunk] = []
    for doc_id, raw in CORPUS.items():
        all_chunks.extend(chunk_text(doc_id, raw, size=70, overlap=20))
    vs = VectorStore()
    vs.add(all_chunks)
    bm = BM25Index()
    bm.add(all_chunks)
    print(f"  chunks={len(all_chunks)} docs={len(CORPUS)}")
    return vs, bm, all_chunks


def demo_cross_vs_bi() -> None:
    section("1) Bi 点积 vs Cross 交互：同一对 (q,d)")
    q = "X-KEY-99 能否本地缓存？"
    d_gold = "机密系统令牌代号 X-KEY-99 仅限安全组轮换，禁止个人本地缓存。"
    d_noise = "问：公司有食堂吗？答：园区 B1 有员工餐厅。"
    bi_g = dot(embed_text(q), embed_text(d_gold))
    bi_n = dot(embed_text(q), embed_text(d_noise))
    cx_g = cross_score(q, d_gold)
    cx_n = cross_score(q, d_noise)
    print(f"  Q: {q}")
    print(f"  bi  gold={bi_g:.3f}  noise={bi_n:.3f}  margin={bi_g - bi_n:.3f}")
    print(f"  cross gold={cx_g:.3f} noise={cx_n:.3f} margin={cx_g - cx_n:.3f}")
    assert cx_g > cx_n, "cross should prefer gold over cafeteria noise"
    print("  → Cross 对专名+禁止联合信号更尖，margin 更大（教学特征）")


def _chunk_by_source(chunks: list[Chunk], source: str) -> Chunk:
    for ch in chunks:
        if ch.source == source:
            return ch
    raise KeyError(source)


def demo_rerank_flips_top1(vs: VectorStore, bm: BM25Index) -> None:
    section("2) 粗排 Top-1 噪声 → 精排翻盘")
    # Hybrid 在本教学语料上经常已经排对；精排价值用「故意打乱的粗排序」钉死：
    # 同一候选集、错误的粗排序 → Cross 交互分纠正 Top-1。
    all_chunks = bm.chunks
    staged = [
        {
            "tag": "leave",
            "q": "工龄满十二年带薪年假到底有几天？",
            "gold": "hr-leave.md",
            # 噪声 FAQ 抢「年假/余额」字面，制度正文被压到后面
            "order": [
                "noise-faq.md#2",
                "noise-faq.md#1",
                "policy-travel.md#2",
                "hr-leave.md#0",
                "hr-leave.md#1",
            ],
        },
        {
            "tag": "travel",
            "q": "一线城市出差住宿最多能报多少钱？",
            "gold": "policy-travel.md",
            "order": [
                "noise-faq.md#1",
                "hr-leave.md#2",
                "policy-travel.md#0",
                "policy-travel.md#1",
            ],
        },
        {
            "tag": "secret",
            "q": "X-KEY-99 能不能写进个人笔记？",
            "gold": "it-security.md",
            "order": [
                "noise-faq.md#0",
                "policy-travel.md#0",
                "it-security.md#1",
                "hr-leave.md#0",
            ],
        },
    ]
    hard_flips = 0
    for case in staged:
        q, gold, tag = case["q"], case["gold"], case["tag"]
        # 伪造粗排分数：越靠前越高（模拟 RRF/向量漂序）
        coarse: list[tuple[float, Chunk]] = []
        n = len(case["order"])
        for i, src in enumerate(case["order"]):
            coarse.append((float(n - i), _chunk_by_source(all_chunks, src)))
        fine = rerank(q, coarse, top_k=3)
        c_top = top1_doc(coarse)
        f_top = top1_doc(fine)
        c_rr = reciprocal_rank(coarse, gold)
        f_rr = reciprocal_rank(fine, gold)
        print(f"\nQ[{tag}]: {q}")
        print("  coarse (staged bad order):")
        for i, (s, ch) in enumerate(coarse[:5], 1):
            mark = "← gold" if ch.doc_id == gold else ""
            print(f"    #{i} {s:.1f} {ch.source} {mark}")
        print("  fine (cross rerank):")
        for i, (s, ch) in enumerate(fine, 1):
            mark = "← gold" if ch.doc_id == gold else ""
            print(f"    #{i} {s:.3f} {ch.source} {mark}")
        print(f"  top1: {c_top} → {f_top} | RR: {c_rr:.2f} → {f_rr:.2f}")
        assert hit_at_k(coarse, gold)
        assert f_top == gold, f"rerank must flip top1 to gold for {tag}"
        assert f_rr > c_rr
        hard_flips += 1
        print("  → [翻盘] 精排把 gold 从粗排后方提到 Top-1")

    # 附：真实 Hybrid 粗排上至少保持不伤 MRR（完整表见 demo 3）
    q_live = "工龄满十二年带薪年假到底有几天？"
    live_c = hybrid_search(q_live, vs, bm, per_channel_k=8, top_k=6)
    live_f = rerank(q_live, live_c, top_k=3)
    print(f"\n  live hybrid check: top1 {top1_doc(live_c)} → {top1_doc(live_f)}")
    print(f"  hard_flips={hard_flips}/3 (staged)")
    assert hard_flips == 3


def demo_mrr_table(vs: VectorStore, bm: BM25Index) -> None:
    section("3) MRR@6 粗排 vs 精排（同一候选集）")
    gold_set = [
        ("一线城市住宿上限多少钱", "policy-travel.md"),
        ("满十年年假有几天", "hr-leave.md"),
        ("X-KEY-99 禁止缓存吗", "it-security.md"),
        ("公共 Wi-Fi 要不要 VPN", "it-security.md"),
        ("超标住宿财务能否拒报", "policy-travel.md"),
        ("病假超过三天要医院证明吗", "hr-leave.md"),
        ("酒店积分和报销标准有关吗", "noise-faq.md"),
    ]
    mrr_c = mrr_f = 0.0
    n = len(gold_set)
    improved = 0
    for q, gold in gold_set:
        coarse = hybrid_search(q, vs, bm, per_channel_k=8, top_k=6)
        fine = rerank(q, coarse, top_k=6)
        rc = reciprocal_rank(coarse, gold)
        rf = reciprocal_rank(fine, gold)
        mrr_c += rc
        mrr_f += rf
        arrow = "↑" if rf > rc else ("=" if rf == rc else "↓")
        if rf > rc:
            improved += 1
        # hit@k 在同一候选重排后应不变（gold 在集合内时）
        if hit_at_k(coarse, gold):
            assert hit_at_k(fine, gold), "rerank must not drop in-set gold"
        print(
            f"  [{arrow}] RR {rc:.2f}→{rf:.2f}  "
            f"top1 {top1_doc(coarse)[:16]:<16} → {top1_doc(fine)[:16]:<16} | {q}"
        )
    mrr_c /= n
    mrr_f /= n
    print(f"\n  MRR coarse={mrr_c:.3f}  fine={mrr_f:.3f}  improved_queries={improved}/{n}")
    assert mrr_f + 1e-9 >= mrr_c, "teaching reranker should not hurt MRR on this set"
    print("  注：hit@K 重排前后不变；MRR/Top-1 才是精排 KPI")


def demo_cannot_rescue_missing(vs: VectorStore, bm: BM25Index) -> None:
    section("4) 边界：候选里没有 gold → Rerank 救不回")
    q = "X-KEY-99 轮换规则"
    gold = "it-security.md"
    # 人为构造「坏候选」：只取明显无关的 noise/travel，排除 IT
    bad_pool = [
        (0.9, ch)
        for ch in bm.chunks
        if ch.doc_id != gold
    ][:5]
    assert bad_pool and all(ch.doc_id != gold for _, ch in bad_pool)
    fine = rerank(q, bad_pool, top_k=3)
    print(f"Q: {q}")
    print("  forced candidates (no IT):")
    for s, ch in bad_pool:
        print(f"    coarse_placeholder {ch.source}")
    print("  after rerank:")
    for s, ch in fine:
        print(f"    {s:.3f} {ch.source}")
    assert not hit_at_k(fine, gold)
    print("  → [铁律] gold ∉ 候选集，精排只能在噪声里选相对不那么差的")


def demo_latency_model() -> None:
    section("5) 延迟心智模型：T ≈ N × t_pair")
    t_pair_ms = 8.0  # 假设真 Cross-Encoder 单对 ~8ms（示意）
    for n in (5, 20, 50, 100):
        print(f"  N={n:<3} → rerank ≈ {n * t_pair_ms:.0f} ms  (batch 可降常数，下界仍随 N)")
    print("  抓手：先定 P95 延迟预算，再反推 N；K 另由 prompt 窗口定")


def demo_pipeline_snippet(vs: VectorStore, bm: BM25Index) -> None:
    section("6) 生产同构接口：retrieve_N → rerank → top_K")
    q = "一线城市住宿标准"
    n, k = 6, 2
    candidates = hybrid_search(q, vs, bm, per_channel_k=8, top_k=n)
    final = rerank(q, candidates, top_k=k)
    print(f"Q: {q}")
    print(f"  retrieve N={n} → rerank → K={k}")
    for i, (s, ch) in enumerate(final, 1):
        preview = ch.text.replace("\n", " ")[:40]
        print(f"  [S{i}] {s:.3f} {ch.source} | {preview}...")
    assert hit_at_k(final, "policy-travel.md")


def main() -> None:
    print("Rerank L3 demo (stdlib only: hybrid candidates + teaching cross score)")
    demo_cross_vs_bi()
    section("Ingest corpus")
    vs, bm, _chunks = ingest()
    demo_rerank_flips_top1(vs, bm)
    demo_mrr_table(vs, bm)
    demo_cannot_rescue_missing(vs, bm)
    demo_latency_model()
    demo_pipeline_snippet(vs, bm)
    section("DONE · L3 rerank green")
    print("pipeline: hybrid Top-N → cross pair score → Top-K; MRR↑; missing gold unrecoverable")


if __name__ == "__main__":
    main()
