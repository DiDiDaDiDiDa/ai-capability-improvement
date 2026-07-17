#!/usr/bin/env python3
"""
上下文工程对照 Demo（L5）。
纯 Python 标准库：检索之后、喂 LLM 之前，修「上下文本身」。

定位：
  L4 Query   修「提问本身」（检索之前）
  L2 Hybrid  修「召回通道」
  L3 Rerank  修「候选内的序」
  L5 Context 修「喂进 LLM 的上下文」（检索之后）——本层

三个抓手：
  1) Parent-Child   小块检索（精准）→ 返回大块（完整上下文）
  2) Compression    逐句按相关性过滤，压掉无关句，省 token 降噪
  3) Lost-in-middle U 型注意力：gold 落中间会被忽略，重排到两端缓解

运行: python3 context_eng_demo.py
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------------------
# 0) 语料：与 L2/L3/L4 完全对齐
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
# 1) primitives（tokenize/embed 与前几层同构；Chunk 增加 parent 归属）
# ---------------------------------------------------------------------------

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


def embed_text(text: str, dim: int = 128, ngram: int = 2) -> list[float]:
    t = re.sub(r"\s+", "", text.lower())
    if not t:
        return [0.0] * dim
    vec = [0.0] * dim
    grams = [t] if len(t) < ngram else [t[i : i + ngram] for i in range(len(t) - ngram + 1)]
    for g in grams:
        import hashlib

        idx = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:8], 16) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_sentences(text: str) -> list[str]:
    """按中文标点切句，用于 Parent 内部的 Child 粒度与压缩。"""
    parts = re.split(r"(?<=[。；！？\n])", clean_text(text))
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# 2) Parent-Child：child=句子（检索单元），parent=整篇文档（生成单元）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Child:
    doc_id: str
    child_id: int
    text: str

    @property
    def uid(self) -> str:
        return f"{self.doc_id}#c{self.child_id}"


@dataclass
class ParentChildStore:
    """
    child 检索用 Hybrid(BM25+Vector+RRF)——与 L2/L3/L4 对齐。
    纯向量在短句上向量稀疏、哈希碰撞严重（专名/数字信号被淹没），
    句子粒度尤其依赖 BM25 的关键词强信号。
    """

    parents: dict[str, str] = field(default_factory=dict)          # doc_id -> 整篇
    children: list[Child] = field(default_factory=list)
    vecs: list[list[float]] = field(default_factory=list)
    tf: list[Counter] = field(default_factory=list)
    doc_len: list[int] = field(default_factory=list)
    df: Counter = field(default_factory=Counter)
    avgdl: float = 0.0
    k1: float = 1.5
    b: float = 0.75

    def build(self, corpus: dict[str, str]) -> None:
        for doc_id, raw in corpus.items():
            self.parents[doc_id] = clean_text(raw)
            for i, sent in enumerate(split_sentences(raw)):
                self.children.append(Child(doc_id, i, sent))
                self.vecs.append(embed_text(sent))
                terms = tokenize(sent)
                c = Counter(terms)
                self.tf.append(c)
                self.doc_len.append(len(terms))
                for t in c:
                    self.df[t] += 1
        n = len(self.children)
        self.avgdl = sum(self.doc_len) / n if n else 0.0

    def _bm25(self, query: str, i: int) -> float:
        q_terms = tokenize(query)
        if not q_terms or self.avgdl <= 0:
            return 0.0
        n, dl, tfs, s = len(self.children), self.doc_len[i], self.tf[i], 0.0
        for t in q_terms:
            f = tfs.get(t, 0)
            if f <= 0:
                continue
            idf = math.log(1.0 + (n - self.df.get(t, 0) + 0.5) / (self.df.get(t, 0) + 0.5))
            denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
            s += idf * (f * (self.k1 + 1.0)) / denom
        return s

    def retrieve_child(self, query: str, top_k: int = 3) -> list[tuple[float, Child]]:
        n = len(self.children)
        qv = embed_text(query)
        vec_rank = sorted(range(n), key=lambda i: dot(qv, self.vecs[i]), reverse=True)
        bm_scored = [(self._bm25(query, i), i) for i in range(n)]
        bm_rank = [i for s, i in sorted(bm_scored, key=lambda x: x[0], reverse=True) if s > 0]
        # RRF 融合两路排名
        rrf: dict[int, float] = {}
        for rank, i in enumerate(vec_rank, start=1):
            rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank)
        for rank, i in enumerate(bm_rank, start=1):
            rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank)
        fused = sorted(rrf.items(), key=lambda x: x[1], reverse=True)
        return [(score, self.children[i]) for i, score in fused[:top_k]]

    def retrieve_parent(self, query: str, top_k: int = 2) -> list[str]:
        """小块命中 → 去重上卷到 parent，返回完整父块（喂 LLM 的上下文）。"""
        seen: set[str] = set()
        parents: list[str] = []
        for _s, ch in self.retrieve_child(query, top_k=top_k * 3):
            if ch.doc_id not in seen:
                seen.add(ch.doc_id)
                parents.append(ch.doc_id)
            if len(parents) >= top_k:
                break
        return parents


@dataclass
class FlatDocStore:
    """对照组：直接把整篇文档 embed 成一个大块检索（无 child 粒度）。"""

    doc_ids: list[str] = field(default_factory=list)
    vecs: list[list[float]] = field(default_factory=list)

    def build(self, corpus: dict[str, str]) -> None:
        for doc_id, raw in corpus.items():
            self.doc_ids.append(doc_id)
            self.vecs.append(embed_text(clean_text(raw)))

    def retrieve(self, query: str, top_k: int = 2) -> list[str]:
        qv = embed_text(query)
        scored = [(dot(qv, self.vecs[i]), self.doc_ids[i]) for i in range(len(self.doc_ids))]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _s, d in scored[:top_k]]


# ---------------------------------------------------------------------------
# 3) Context Compression：逐句按相关性打分，只留 top 句，省 token 降噪
# ---------------------------------------------------------------------------

def sentence_relevance(query: str, sent: str) -> float:
    """词覆盖 + 字符 bigram Jaccard，模拟压缩器对句子的相关性打分。"""
    q, d = set(tokenize(query)), set(tokenize(sent))
    if not q or not d:
        return 0.0
    cover = len(q & d) / len(q)
    qf, df = re.sub(r"\s+", "", query.lower()), re.sub(r"\s+", "", sent.lower())
    qb = {qf[i : i + 2] for i in range(max(0, len(qf) - 1))}
    db = {df[i : i + 2] for i in range(max(0, len(df) - 1))}
    jacc = len(qb & db) / len(qb | db) if (qb or db) else 0.0
    return 2.0 * cover + jacc


def compress_context(query: str, parent_text: str, keep: int = 2) -> str:
    """从 parent 里挑出与 query 最相关的 keep 句，丢掉无关句。"""
    sents = [s for s in split_sentences(parent_text) if not s.startswith("#")]
    scored = sorted(sents, key=lambda s: sentence_relevance(query, s), reverse=True)
    picked = [s for s in scored[:keep] if sentence_relevance(query, s) > 0]
    # 保持原文顺序输出，可读性更好
    return "".join(s for s in sents if s in picked)


def approx_tokens(text: str) -> int:
    return len(tokenize(text))


# ---------------------------------------------------------------------------
# 4) Lost-in-the-middle：U 型位置权重 + 重排缓解
# ---------------------------------------------------------------------------

def position_weight(pos: int, n: int) -> float:
    """
    U 型注意力（Liu et al. 2023 的教学化模型）：
    首尾权重高、中间低。pos ∈ [0, n-1]。
    """
    if n <= 1:
        return 1.0
    x = pos / (n - 1)  # 0..1
    # U 型：两端 1.0，中间 ~0.4
    return 0.4 + 0.6 * abs(2 * x - 1)


def reorder_edges(items: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """
    把高相关块排到两端（缓解 lost-in-the-middle）：
    最相关放头，次相关放尾，其余塞中间。
    """
    ranked = sorted(items, key=lambda x: x[0], reverse=True)
    head: list[tuple[float, str]] = []
    tail: list[tuple[float, str]] = []
    for i, it in enumerate(ranked):
        (head if i % 2 == 0 else tail).append(it)
    return head + list(reversed(tail))


def effective_signal(order: list[tuple[float, str]]) -> float:
    """上下文有效信号 = Σ 相关性 × 位置权重。越高说明关键信息越可能被读到。"""
    n = len(order)
    return sum(rel * position_weight(i, n) for i, (rel, _t) in enumerate(order))


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def demo_parent_child() -> None:
    section("1) Parent-Child：小块检索精准，大块喂 LLM 完整")
    pc = ParentChildStore()
    pc.build(CORPUS)
    flat = FlatDocStore()
    flat.build(CORPUS)
    cases = [
        ("工龄满二十年年假多少天", "hr-leave.md"),
        ("一线城市住宿报销上限", "policy-travel.md"),
        ("公共网络要开 VPN 吗", "it-security.md"),
    ]
    pc_hit = flat_hit = 0
    for q, gold in cases:
        top_child = pc.retrieve_child(q, top_k=1)[0][1]
        pc_parents = pc.retrieve_parent(q, top_k=2)
        flat_docs = flat.retrieve(q, top_k=2)
        pc_ok = pc_parents[0] == gold
        flat_ok = flat_docs[0] == gold
        pc_hit += pc_ok
        flat_hit += flat_ok
        print(f"\nQ: {q}")
        print(f"  child 命中句: [{top_child.doc_id}] {top_child.text}")
        print(f"  parent-child top1={pc_parents[0]:<18} {'HIT' if pc_ok else 'MISS'}")
        print(f"  flat-doc     top1={flat_docs[0]:<18} {'HIT' if flat_ok else 'MISS'}")
    print(f"\n  Parent-Child top1 命中 {pc_hit}/{len(cases)} | Flat-Doc {flat_hit}/{len(cases)}")
    assert pc_hit >= flat_hit, "小块检索精度应不低于整篇大块"
    assert pc_hit == len(cases), "Parent-Child 三题应全部 top1"
    print("  → child 句粒度检索更准，返回 parent 整篇保证 LLM 拿到完整上下文")


def demo_compression() -> None:
    section("2) Context Compression：压掉无关句，省 token 降噪")
    q = "一线城市住宿报销上限多少"
    parent = CORPUS["policy-travel.md"]
    compressed = compress_context(q, parent, keep=2)
    t_before, t_after = approx_tokens(parent), approx_tokens(compressed)
    print(f"Q: {q}")
    print(f"  原 parent tokens={t_before}")
    print(f"  压缩后 tokens={t_after}  (保留句)")
    print(f"    {compressed}")
    assert "500" in compressed, "压缩必须保留含答案（500 元）的句子"
    assert t_after < t_before, "压缩后 token 数必须下降"
    ratio = t_after / t_before
    print(f"  → 压缩比 {ratio:.0%}，答案句保留，噪声句（餐饮/加班）丢弃")


def demo_lost_in_middle() -> None:
    section("3) Lost-in-the-middle：U 型注意力 + 重排缓解")
    # 5 个候选块，相关性已知；gold（rel=1.0）故意放中间
    rels = [0.2, 0.3, 1.0, 0.25, 0.15]  # index 2 是 gold，居中
    labels = [f"blk{i}(rel={r})" for i, r in enumerate(rels)]
    naive_order = list(zip(rels, labels))
    reordered = reorder_edges(naive_order)

    def gold_pos(order: list[tuple[float, str]]) -> int:
        return max(range(len(order)), key=lambda i: order[i][0])

    p_naive, p_re = gold_pos(naive_order), gold_pos(reordered)
    n = len(rels)
    w_naive = position_weight(p_naive, n)
    w_re = position_weight(p_re, n)
    sig_naive, sig_re = effective_signal(naive_order), effective_signal(reordered)
    print("  U 型位置权重:", [f"{position_weight(i, n):.2f}" for i in range(n)])
    print(f"  naive  : gold@pos{p_naive} 权重={w_naive:.2f}  有效信号={sig_naive:.3f}")
    print(f"  reorder: gold@pos{p_re} 权重={w_re:.2f}  有效信号={sig_re:.3f}")
    print("  重排后顺序:", [lab for _r, lab in reordered])
    assert w_re > w_naive, "重排应把 gold 挪到高权重的两端"
    assert sig_re > sig_naive, "重排后上下文有效信号应上升"
    print(f"  → gold 从中间(权重{w_naive:.2f})挪到边缘(权重{w_re:.2f})，有效信号 {sig_naive:.3f}→{sig_re:.3f}")


def main() -> None:
    print("Context-Eng L5 demo (stdlib only: parent-child / compression / lost-in-middle)")
    demo_parent_child()
    demo_compression()
    demo_lost_in_middle()
    section("DONE · L5 context-eng green")
    print("pipeline: retrieve child → 上卷 parent → 压缩 → 重排两端 → 喂 LLM")


if __name__ == "__main__":
    main()
