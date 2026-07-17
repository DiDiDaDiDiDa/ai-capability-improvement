#!/usr/bin/env python3
"""
Query 优化对照 Demo（L4）。
纯 Python 标准库：在「检索之前」改造 query —— Rewrite / HyDE / Multi-Query / Self-Query。

定位：
  L2 Hybrid  修「召回通道」（BM25 + Vector + RRF）
  L3 Rerank  修「候选内的序」（Cross 交互精排）
  L4 Query   修「提问本身」（口语化 / 词表错配 / 缺过滤条件）—— 发生在检索之前

链路: raw query → [rewrite/HyDE/multi/self] → Hybrid retrieve → 对照 RR/命中

运行: python3 query_opt_demo.py
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable


# ---------------------------------------------------------------------------
# 0) 语料：与 L2/L3 完全对齐（同一套四篇 + 三路对照底座）
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
# 1) 检索层 primitives（与 L2/L3 同构，自包含）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: int
    text: str

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
            chunks.append(Chunk(doc_id, idx, piece))
            idx += 1
        if end >= n:
            break
        start += step
    return chunks


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|[一-鿿]+", re.UNICODE)


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
    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % dim


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
            self.chunks.append(ch)
            self.doc_len.append(len(terms))
            c = Counter(terms)
            self.tf.append(c)
            for t in c:
                self.df[t] += 1
        self.n_docs = len(self.chunks)
        self.avgdl = sum(self.doc_len) / self.n_docs if self.n_docs else 0.0

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(self, query: str, i: int) -> float:
        q_terms = tokenize(query)
        if not q_terms or self.avgdl <= 0:
            return 0.0
        dl, tfs, s = self.doc_len[i], self.tf[i], 0.0
        for t in q_terms:
            f = tfs.get(t, 0)
            if f <= 0:
                continue
            denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
            s += self.idf(t) * (f * (self.k1 + 1.0)) / denom
        return s

    def search(self, query: str, top_k: int = 5) -> list[tuple[float, Chunk]]:
        scored = [(self.score(query, i), self.chunks[i]) for i in range(self.n_docs)]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x for x in scored if x[0] > 0][:top_k]


@dataclass
class VectorStore:
    items: list[tuple[Chunk, list[float]]] = field(default_factory=list)

    def add(self, chunks: Iterable[Chunk]) -> None:
        for c in chunks:
            self.items.append((c, embed_text(c.text)))

    def search(self, query: str, top_k: int = 5) -> list[tuple[float, Chunk]]:
        qv = embed_text(query)
        scored = [(dot(qv, v), c) for c, v in self.items]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


def rrf_fuse(
    ranked_lists: list[list[tuple[float, Chunk]]],
    k: int = 60,
    top_k: int = 5,
) -> list[tuple[float, Chunk]]:
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, Chunk] = {}
    for ranked in ranked_lists:
        for rank, (_raw, ch) in enumerate(ranked, start=1):
            scores[ch.uid] += 1.0 / (k + rank)
            best[ch.uid] = ch
    fused = [(scores[u], best[u]) for u in scores]
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
# 2) 指标
# ---------------------------------------------------------------------------

def hit_at_k(hits: list[tuple[float, Chunk]], gold_doc: str) -> bool:
    return any(ch.doc_id == gold_doc for _, ch in hits)


def reciprocal_rank(hits: list[tuple[float, Chunk]], gold_doc: str) -> float:
    for i, (_s, ch) in enumerate(hits, start=1):
        if ch.doc_id == gold_doc:
            return 1.0 / i
    return 0.0


def rank_of(hits: list[tuple[float, Chunk]], gold_doc: str) -> int:
    for i, (_s, ch) in enumerate(hits, start=1):
        if ch.doc_id == gold_doc:
            return i
    return 0  # 0 = miss


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def ingest() -> tuple[VectorStore, BM25Index]:
    all_chunks: list[Chunk] = []
    for doc_id, raw in CORPUS.items():
        all_chunks.extend(chunk_text(doc_id, raw, size=70, overlap=20))
    vs, bm = VectorStore(), BM25Index()
    vs.add(all_chunks)
    bm.add(all_chunks)
    print(f"  chunks={len(all_chunks)} docs={len(CORPUS)}")
    return vs, bm


# ---------------------------------------------------------------------------
# 3) 四种 Query 优化（教学版：用规则模拟 LLM 改写，非真 LLM 调用）
#    生产里这一层是 LLM prompt；这里用确定性规则复现「改写→检索改善」的因果。
# ---------------------------------------------------------------------------

# 口语 → 制度术语 同义词表（模拟 LLM rewrite 的知识）
_SYNONYM: list[tuple[str, str]] = [
    ("白拿", "带薪"),
    ("不上班的假", "年假"),
    ("不用上班", "年假"),
    ("带薪假", "带薪年假"),
    ("老员工", "工龄满"),
    ("干了", "工龄"),
    ("多少天", "天数"),
    ("几天", "天数"),
    ("报多少", "报销 标准 上限"),
    ("能报多少钱", "报销 标准 上限"),
    ("连公共网络", "公共 Wi-Fi"),
    ("蹭网", "公共 Wi-Fi"),
    ("翻墙工具", "VPN"),
    ("那个密钥", "X-KEY-99 令牌"),
    ("存本地", "本地缓存"),
]


def rewrite_query(raw: str) -> str:
    """
    Query Rewrite：把口语化提问归一到制度术语。
    生产等价物：LLM「请把用户问题改写为检索友好的规范表达」。
    """
    q = raw
    extra: list[str] = []
    for spoken, formal in _SYNONYM:
        if spoken in q:
            extra.append(formal)
    # 保留原问 + 追加术语，避免改写丢信息
    return (q + " " + " ".join(extra)).strip() if extra else q


# HyDE：为每类意图预置「假想答案」模板（模拟 LLM 先答后检索）
_HYDE_TEMPLATES: list[tuple[tuple[str, ...], str]] = [
    (("年假", "带薪", "工龄", "老员工", "白拿", "不上班的假"),
     "正式员工享有带薪年假，工龄满 10 年 10 天，满 20 年 15 天，天数以制度为准。"),
    (("住宿", "报销", "出差", "差旅", "报多少"),
     "差旅住宿标准：一线城市每晚不超过 500 元，超标未批财务拒报。"),
    (("vpn", "wifi", "wi-fi", "公共", "蹭网", "翻墙"),
     "公共 Wi-Fi 下必须开启公司 VPN，防止数据泄露。"),
    (("x-key-99", "令牌", "密钥", "缓存", "存本地"),
     "机密令牌 X-KEY-99 仅限安全组轮换，禁止个人本地缓存。"),
]


def hyde_query(raw: str) -> str:
    """
    HyDE（Hypothetical Document Embeddings）：先造一段假想答案，用它去检索。
    动机：短问题的字符分布与「答案型文档」差异大；假答案更贴近 doc 语域。
    生产等价物：LLM「先写一段可能的答案」，再 embed 假答案检索。
    """
    low = raw.lower()
    flat = re.sub(r"\s+", "", low)
    for keys, hypo in _HYDE_TEMPLATES:
        if any(k in flat or k in low for k in keys):
            return hypo
    return raw  # 命不中意图则退回原问（诚实：HyDE 不是万能）


def multi_query(raw: str) -> list[str]:
    """
    Multi-Query：一问改写成多个视角，各自检索后 RRF 融合，扩大召回面。
    生产等价物：LLM「生成 3 个语义等价但措辞不同的检索式」。
    这里 = 原问 + rewrite 版 + HyDE 版（去重）。
    """
    variants = [raw, rewrite_query(raw), hyde_query(raw)]
    seen: set[str] = set()
    uniq: list[str] = []
    for v in variants:
        key = re.sub(r"\s+", "", v)
        if key and key not in seen:
            seen.add(key)
            uniq.append(v)
    return uniq


def multi_query_search(
    raw: str, vs: VectorStore, bm: BM25Index, top_k: int = 5
) -> list[tuple[float, Chunk]]:
    """对每个改写式各跑一次 Hybrid，再把多路结果 RRF 融合。"""
    per_variant = [hybrid_search(v, vs, bm, per_channel_k=8, top_k=top_k) for v in multi_query(raw)]
    return rrf_fuse(per_variant, k=60, top_k=top_k)


# Self-Query：从问题里抽结构化过滤条件（topic），检索前先按 doc 过滤
_TOPIC_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("hr-leave.md", ("年假", "带薪", "工龄", "病假", "事假", "调休", "休假", "白拿", "不上班的假")),
    ("policy-travel.md", ("差旅", "住宿", "报销", "出差", "餐饮", "发票", "报多少")),
    ("it-security.md", ("vpn", "wifi", "wi-fi", "密钥", "令牌", "x-key-99", "钓鱼", "安全")),
]


def self_query_topic(raw: str) -> str | None:
    """从口语问题里推断 metadata 过滤条件（这里是 doc 归属 topic）。"""
    low = raw.lower()
    flat = re.sub(r"\s+", "", low)
    best_doc, best_hit = None, 0
    for doc_id, keys in _TOPIC_RULES:
        hit = sum(1 for k in keys if k in flat or k in low)
        if hit > best_hit:
            best_doc, best_hit = doc_id, hit
    return best_doc


def self_query_search(
    raw: str, vs: VectorStore, bm: BM25Index, top_k: int = 5
) -> tuple[list[tuple[float, Chunk]], str | None]:
    """
    Self-Query：先抽 topic 过滤，再在过滤后的子集里检索。
    生产等价物：LLM「从问题里抽出 where 条件」→ 向量库带 metadata filter 检索。
    这里用改写后的 query 检索、再按 topic 过滤候选，压制跨库噪声。
    """
    topic = self_query_topic(raw)
    fused = hybrid_search(rewrite_query(raw), vs, bm, per_channel_k=8, top_k=top_k * 3)
    if topic:
        filtered = [(s, ch) for s, ch in fused if ch.doc_id == topic]
        if filtered:
            return filtered[:top_k], topic
    return fused[:top_k], topic


def _show(tag: str, hits: list[tuple[float, Chunk]], gold: str) -> tuple[int, float]:
    r = rank_of(hits, gold)
    rr = reciprocal_rank(hits, gold)
    top = hits[0][1].source if hits else "—"
    flag = "HIT" if r == 1 else (f"@{r}" if r else "MISS")
    print(f"  {tag:<10} top1={top:<18} gold={flag:<5} RR={rr:.3f}")
    return r, rr


def demo_rewrite(vs: VectorStore, bm: BM25Index) -> None:
    section("1) Query Rewrite：口语化 → 制度术语")
    q = "老员工白拿几天不上班的假？"
    gold = "hr-leave.md"
    print(f"Q(raw): {q}")
    print(f"  rewrite → {rewrite_query(q)}")
    r0, _ = _show("raw", hybrid_search(q, vs, bm, top_k=5), gold)
    r1, _ = _show("rewrite", hybrid_search(rewrite_query(q), vs, bm, top_k=5), gold)
    assert r0 >= 2 and r1 == 1, "钉死：raw 把 gold 压到 @2+，rewrite 翻回 top1"
    print("  → 口语词无字面重合，raw 被 FAQ 抢序；改写注入制度术语翻回 top1")


def demo_hyde(vs: VectorStore, bm: BM25Index) -> None:
    section("2) HyDE：先造假想答案再检索")
    q = "蹭公共网络要不要开那个翻墙工具？"
    gold = "it-security.md"
    print(f"Q(raw): {q}")
    print(f"  HyDE  → {hyde_query(q)}")
    r0, _ = _show("raw", hybrid_search(q, vs, bm, top_k=5), gold)
    r1, _ = _show("hyde", hybrid_search(hyde_query(q), vs, bm, top_k=5), gold)
    assert r0 >= 2 and r1 == 1, "钉死：raw 把 gold 压到 @2+，HyDE 翻回 top1"
    print("  → 假想答案贴近 doc 语域，把 VPN 制度页从 @2+ 拉回 top1")


def demo_multi_query(vs: VectorStore, bm: BM25Index) -> None:
    section("3) Multi-Query：多视角改写 + RRF 融合")
    q = "老员工出差报多少"  # 跨 topic 模糊问法：raw 被「年假」页抢 top1
    gold = "policy-travel.md"
    print(f"Q(raw): {q}")
    for i, v in enumerate(multi_query(q), 1):
        print(f"  变体{i}: {v}")
    r0, _ = _show("raw", hybrid_search(q, vs, bm, top_k=5), gold)
    r1, _ = _show("multi", multi_query_search(q, vs, bm, top_k=5), gold)
    assert r0 >= 2 and r1 == 1, "钉死：raw 把 gold 压到 @2+，multi 融合翻回 top1"
    print("  → 单一问法被邻库抢序；多变体并检 + RRF 把差旅正文顶回 top1")


def demo_self_query(vs: VectorStore, bm: BM25Index) -> None:
    section("4) Self-Query：抽 topic 过滤压制跨库噪声")
    q = "年假余额到底几天？"  # noise-faq 也含「年假/余额」抢字面
    gold = "hr-leave.md"
    print(f"Q(raw): {q}")
    topic = self_query_topic(q)
    print(f"  抽取过滤条件 topic = {topic}")
    r0, _ = _show("raw", hybrid_search(q, vs, bm, top_k=5), gold)
    hits, _ = self_query_search(q, vs, bm, top_k=5)
    r1, _ = _show("self-q", hits, gold)
    assert topic == gold, "topic 应正确抽到 hr-leave"
    assert r0 >= 2 and r1 == 1, "钉死：raw 把 gold 压到 @2+，topic 过滤后翻回 top1"
    print("  → FAQ 噪声页含同字面抢序；topic 过滤把候选锁进正确库，翻回 top1")


def demo_summary(vs: VectorStore, bm: BM25Index) -> None:
    section("5) 四路方法 · RR 汇总对照")
    cases = [
        ("老员工白拿几天不上班的假？", "hr-leave.md", "rewrite"),
        ("蹭公共网络要不要开那个翻墙工具？", "it-security.md", "hyde"),
        ("老员工出差报多少", "policy-travel.md", "multi"),
        ("年假余额到底几天？", "hr-leave.md", "self"),
    ]
    print(f"  {'method':<8}{'raw_RR':>8}{'opt_RR':>8}   query")
    total_raw = total_opt = 0.0
    for q, gold, method in cases:
        raw_rr = reciprocal_rank(hybrid_search(q, vs, bm, top_k=5), gold)
        if method == "rewrite":
            opt = hybrid_search(rewrite_query(q), vs, bm, top_k=5)
        elif method == "hyde":
            opt = hybrid_search(hyde_query(q), vs, bm, top_k=5)
        elif method == "multi":
            opt = multi_query_search(q, vs, bm, top_k=5)
        else:
            opt, _ = self_query_search(q, vs, bm, top_k=5)
        opt_rr = reciprocal_rank(opt, gold)
        total_raw += raw_rr
        total_opt += opt_rr
        print(f"  {method:<8}{raw_rr:>8.3f}{opt_rr:>8.3f}   {q}")
    mrr_raw, mrr_opt = total_raw / len(cases), total_opt / len(cases)
    print(f"  {'MRR':<8}{mrr_raw:>8.3f}{mrr_opt:>8.3f}")
    assert mrr_opt >= mrr_raw, "四路优化的整体 MRR 不应低于 raw"
    print(f"  → Query 优化层整体 MRR {mrr_raw:.3f} → {mrr_opt:.3f}")


def main() -> None:
    print("Query-Opt L4 demo (stdlib only: rewrite / HyDE / multi-query / self-query)")
    section("Ingest corpus (与 L2/L3 对齐)")
    vs, bm = ingest()
    demo_rewrite(vs, bm)
    demo_hyde(vs, bm)
    demo_multi_query(vs, bm)
    demo_self_query(vs, bm)
    demo_summary(vs, bm)
    section("DONE · L4 query-opt green")
    print("pipeline: raw query → rewrite/HyDE/multi/self → hybrid retrieve; MRR↑")


if __name__ == "__main__":
    main()
