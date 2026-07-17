#!/usr/bin/env python3
"""
GraphRAG 对照 Demo（L6）。
纯 Python 标准库：实体+关系建图 → 多跳扩展 / 社区检索，对照纯向量。

定位：
  L2 Hybrid  修「召回通道」——找「像」的块
  L3 Rerank  修「候选内的序」
  L4 Query   修「提问本身」
  L5 Context 修「上下文形状」
  L6 Graph   修「跨块关系与全局主题」——找「连」的实体 ——本层

三个抓手：
  1) 实体+关系抽取（教学规则版；生产 = LLM/NER 可热替换）
  2) Local：种子实体 → 多跳邻居 → 上卷源文档（补向量漏的跨块证据）
  3) Global：社区摘要检索（主题级问题，向量只会贴到局部块）

运行: python3 graphrag_demo.py
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------------------
# 0) 语料：与 L2–L5 对齐（同一四篇），关系边从正文抽出
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
# 1) 教学版向量底座（与前层同构，作对照组）
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


@dataclass
class VectorStore:
    """整篇文档向量检索（对照组：只找「像」的块）。"""

    doc_ids: list[str] = field(default_factory=list)
    vecs: list[list[float]] = field(default_factory=list)

    def build(self, corpus: dict[str, str]) -> None:
        for doc_id, raw in corpus.items():
            self.doc_ids.append(doc_id)
            self.vecs.append(embed_text(clean_text(raw)))

    def retrieve(self, query: str, top_k: int = 2) -> list[tuple[float, str]]:
        qv = embed_text(query)
        scored = [(dot(qv, self.vecs[i]), self.doc_ids[i]) for i in range(len(self.doc_ids))]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
# 2) 实体 / 关系抽取（规则教学版；生产用 LLM/NER 热替换 extract_*）
# ---------------------------------------------------------------------------

# 规范实体表：别名 → 规范名（覆盖口语与正文）
ENTITY_ALIASES: dict[str, str] = {
    "出差": "差旅",
    "差旅": "差旅",
    "差途": "差旅",
    "报销": "差旅报销",
    "差旅报销": "差旅报销",
    "住宿": "住宿标准",
    "住宿标准": "住宿标准",
    "年假": "带薪年假",
    "带薪年假": "带薪年假",
    "调休": "调休",
    "加班": "加班",
    "病假": "病假",
    "事假": "事假",
    "vpn": "VPN",
    "VPN": "VPN",
    "wi-fi": "Wi-Fi",
    "Wi-Fi": "Wi-Fi",
    "wifi": "Wi-Fi",
    "公共网络": "Wi-Fi",
    "x-key-99": "X-KEY-99",
    "X-KEY-99": "X-KEY-99",
    "令牌": "X-KEY-99",
    "安全组": "安全组",
    "密钥": "密钥",
    "财务": "财务",
    # 注意：不用 "HR"/"hr" 短别名——会把「HR 系统」噪声页误挂到人事制度
    "人事": "人事制度",
    "人事制度": "人事制度",
}

# 关系模板：(头实体子串, 尾实体子串, 关系类型) — 在同句共现时抽边
RELATION_PATTERNS: list[tuple[str, str, str]] = [
    ("差旅", "加班", "涉及"),
    ("加班", "带薪年假", "不自动折算"),
    ("加班", "调休", "可申请"),
    ("差旅", "人事制度", "调休规则见"),
    ("调休", "带薪年假", "不计入"),
    ("Wi-Fi", "VPN", "必须开启"),
    ("X-KEY-99", "安全组", "仅限轮换"),
    ("钓鱼邮件", "安全组", "上报"),
    ("差旅报销", "财务", "拒报权属"),
    ("住宿标准", "财务", "超标拒报"),
]


@dataclass(frozen=True)
class Triple:
    head: str
    rel: str
    tail: str
    source: str  # doc_id


@dataclass
class KnowledgeGraph:
    """内存图谱：实体 → 邻接边；实体 → 源文档；社区标签。"""

    # entity -> list[(neighbor, rel, source)]
    adj: dict[str, list[tuple[str, str, str]]] = field(default_factory=lambda: defaultdict(list))
    entity_docs: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    triples: list[Triple] = field(default_factory=list)
    # community_id -> set[entity]
    communities: dict[str, set[str]] = field(default_factory=dict)
    # community_id -> summary text
    community_summaries: dict[str, str] = field(default_factory=dict)
    # community_id -> source docs
    community_docs: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def add_triple(self, head: str, rel: str, tail: str, source: str) -> None:
        t = Triple(head, rel, tail, source)
        self.triples.append(t)
        self.adj[head].append((tail, rel, source))
        self.adj[tail].append((head, f"~{rel}", source))  # 无向扩展，便于多跳
        self.entity_docs[head].add(source)
        self.entity_docs[tail].add(source)

    def entities(self) -> set[str]:
        return set(self.adj.keys())


def extract_entities(text: str) -> set[str]:
    """别名表最长匹配 → 规范实体。生产：LLM/NER。"""
    found: set[str] = set()
    lower = text  # 中文为主，保留大小写敏感的专名二次扫
    # 按别名长度降序，避免短别名抢匹配
    for alias in sorted(ENTITY_ALIASES.keys(), key=len, reverse=True):
        if alias.lower() in lower.lower() or alias in text:
            found.add(ENTITY_ALIASES[alias])
    return found


def extract_triples(doc_id: str, text: str) -> list[Triple]:
    """句内共现 + 关系模板。生产：LLM 结构化抽取。"""
    triples: list[Triple] = []
    # 按句切
    sents = re.split(r"[。；！？\n]", text)
    for sent in sents:
        if not sent.strip():
            continue
        ents = extract_entities(sent)
        for h, t, rel in RELATION_PATTERNS:
            if h in ents and t in ents and h != t:
                triples.append(Triple(h, rel, t, doc_id))
    return triples


# 抽象实体 → 落地文档（正文只写「见人事制度」，本体边指到真正的制度页）
ONTOLOGY_DOCS: dict[str, set[str]] = {
    "人事制度": {"hr-leave.md"},
}


def build_graph(corpus: dict[str, str]) -> KnowledgeGraph:
    g = KnowledgeGraph()
    for doc_id, raw in corpus.items():
        text = clean_text(raw)
        # 文档级实体挂载（即使没抽到边，也能从实体回源）
        for e in extract_entities(text):
            g.entity_docs[e].add(doc_id)
            g.adj.setdefault(e, [])
        for tri in extract_triples(doc_id, text):
            g.add_triple(tri.head, tri.rel, tri.tail, tri.source)
    # 本体落地：抽象节点的源文档以权威页为准（覆盖正文「见 XX」造成的误挂）
    for ent, docs in ONTOLOGY_DOCS.items():
        g.entity_docs[ent] = set(docs)
        g.adj.setdefault(ent, [])
    # 社区：按主题手工种子 + 连通扩张（教学版 Louvain 的可读替代）
    seeds = {
        "community-travel": {"差旅", "差旅报销", "住宿标准", "财务"},
        "community-hr": {"带薪年假", "调休", "加班", "病假", "事假", "人事制度"},
        "community-security": {"VPN", "Wi-Fi", "X-KEY-99", "安全组", "密钥"},
    }
    # 把与种子一跳相连的实体吸入社区
    for cid, seed in seeds.items():
        members = set(seed)
        for e in list(seed):
            for nb, _rel, _src in g.adj.get(e, []):
                members.add(nb)
        g.communities[cid] = members
        docs: set[str] = set()
        for e in members:
            docs |= g.entity_docs.get(e, set())
        g.community_docs[cid] = docs
    g.community_summaries = {
        "community-travel": "差旅报销与住宿标准：申请、额度、财务拒报权。",
        "community-hr": "人事休假：带薪年假、调休与加班折算规则；差途加班回公司申请调休。",
        "community-security": "信息安全：公共 Wi-Fi 必须 VPN；X-KEY-99 仅限安全组轮换。",
    }
    return g


# ---------------------------------------------------------------------------
# 3) Local 多跳检索 + Global 社区检索
# ---------------------------------------------------------------------------

def seed_entities_from_query(query: str) -> set[str]:
    return extract_entities(query)


def local_multihop(
    g: KnowledgeGraph,
    query: str,
    hops: int = 2,
    top_k: int = 2,
) -> list[tuple[float, str]]:
    """
    种子实体 → BFS 多跳 → 源文档计分。
    分 = 实体跳数衰减 + 种子-种子边证据 + 本体落地加成。
    """
    seeds = seed_entities_from_query(query)
    if not seeds:
        return []
    # entity -> best (hop distance)
    dist: dict[str, int] = {}
    for e in seeds:
        dist[e] = 0
    frontier = list(dist.keys())
    for _ in range(hops):
        nxt: list[str] = []
        for e in frontier:
            for nb, _rel, _src in g.adj.get(e, []):
                if nb not in dist:
                    dist[nb] = dist[e] + 1
                    nxt.append(nb)
        frontier = nxt
        if not frontier:
            break
    doc_score: Counter = Counter()
    for e, d in dist.items():
        base = 1.0 / (1 + d)
        if e in ONTOLOGY_DOCS:
            # 抽象实体只给权威文档打分，避免「见人事制度」字面所在页抢 top1
            for doc in ONTOLOGY_DOCS[e]:
                doc_score[doc] += base + 2.0
            continue
        for doc in g.entity_docs.get(e, ()):
            doc_score[doc] += base
    # 种子之间已有边：给边的 source 加证据分（关系型问题）
    for t in g.triples:
        if t.head in seeds and t.tail in seeds:
            doc_score[t.source] += 1.0
        elif t.head in dist and t.tail in dist and (t.head in seeds or t.tail in seeds):
            # 一端是种子、一端在扩展集：弱证据
            doc_score[t.source] += 0.3
    # 稳定排序：分高优先，同分按 doc_id，杜绝 set 迭代顺序漂 top1
    ranked = sorted(doc_score.items(), key=lambda x: (-x[1], x[0]))
    return [(float(s), d) for d, s in ranked[:top_k]]


def global_community_retrieve(
    g: KnowledgeGraph,
    query: str,
    top_k: int = 1,
) -> list[tuple[float, str, str]]:
    """
    用社区摘要向量 + 实体重合打分，返回 (score, community_id, summary)。
    主题级问题走 Global，不陷进局部块。
    """
    q_ents = seed_entities_from_query(query)
    qv = embed_text(query)
    scored: list[tuple[float, str, str]] = []
    for cid, summary in g.community_summaries.items():
        vec_s = dot(qv, embed_text(summary))
        overlap = len(q_ents & g.communities.get(cid, set()))
        score = vec_s + 0.5 * overlap
        scored.append((score, cid, summary))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]


def graph_retrieve_docs(g: KnowledgeGraph, query: str, top_k: int = 2) -> list[str]:
    """统一出口：Local 多跳为主；若 query 像主题问法则混入 Global 社区文档。"""
    local = local_multihop(g, query, hops=2, top_k=top_k)
    # 主题触发词 → 强化 global
    topicish = any(k in query for k in ("哪些", "相关制度", "整体", "汇总", "体系"))
    docs: list[str] = []
    seen: set[str] = set()
    if topicish:
        for _s, cid, _sum in global_community_retrieve(g, query, top_k=1):
            for d in sorted(g.community_docs.get(cid, ())):
                if d not in seen and d != "noise-faq.md":
                    seen.add(d)
                    docs.append(d)
                if len(docs) >= top_k:
                    return docs
    for _s, d in local:
        if d not in seen:
            seen.add(d)
            docs.append(d)
        if len(docs) >= top_k:
            break
    return docs


# ---------------------------------------------------------------------------
# 4) Demo + 断言（先观测再钉死）
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def demo_extract(g: KnowledgeGraph) -> None:
    section("1) 实体+关系抽取 → 内存图谱")
    print(f"  实体数: {len(g.entities())}")
    print(f"  三元组数: {len(g.triples)}")
    for t in g.triples[:8]:
        print(f"    ({t.head}) -[{t.rel}]-> ({t.tail})  @{t.source}")
    if len(g.triples) > 8:
        print(f"    ... +{len(g.triples) - 8} more")
    print(f"  社区: {list(g.communities.keys())}")
    for cid, members in g.communities.items():
        print(f"    {cid}: {sorted(members)[:6]}{'...' if len(members) > 6 else ''}")
    assert len(g.triples) >= 4, "至少抽出 4 条关系边"
    assert "X-KEY-99" in g.entities(), "专名实体应入库"
    assert any(t.head == "X-KEY-99" and t.tail == "安全组" for t in g.triples), (
        "X-KEY-99→安全组 边必须存在"
    )
    print("  → 规则抽取可热替换为 LLM/NER；图结构与检索 API 不变")


def demo_local_vs_vector(g: KnowledgeGraph, vs: VectorStore) -> None:
    section("2) Local 多跳 vs 纯向量：跨块关系题")
    # 设计：多跳/关系题 —— 答案依赖「边」与本体落地，不是字面「像」
    cases = [
        # 差旅正文写「调休规则见人事制度」→ 本体落到 hr-leave；向量常贴 policy 字面
        ("调休规则见的人事制度里年假怎么规定", "hr-leave.md"),
        # 专名关系：X-KEY-99 仅限安全组
        ("X-KEY-99 谁能轮换", "it-security.md"),
        # Wi-Fi → VPN 一跳
        ("公共 Wi-Fi 要开什么", "it-security.md"),
    ]
    graph_hit = vec_hit = flips = 0
    for q, gold in cases:
        g_docs = graph_retrieve_docs(g, q, top_k=2)
        v_docs = [d for _s, d in vs.retrieve(q, top_k=2)]
        g_ok = bool(g_docs) and g_docs[0] == gold
        v_ok = bool(v_docs) and v_docs[0] == gold
        graph_hit += g_ok
        vec_hit += v_ok
        if g_ok and not v_ok:
            flips += 1
        seeds = seed_entities_from_query(q)
        print(f"\nQ: {q}")
        print(f"  seeds: {sorted(seeds)}")
        print(f"  graph top: {g_docs}  {'HIT' if g_ok else 'MISS'}")
        print(f"  vector top: {v_docs}  {'HIT' if v_ok else 'MISS'}")
    print(f"\n  Graph top1 {graph_hit}/{len(cases)} | Vector {vec_hit}/{len(cases)} | flips(G✓V✗)={flips}")
    assert graph_hit == len(cases), "Graph 多跳三题应全部 top1"
    assert graph_hit >= vec_hit, "图谱应不低于纯向量"
    assert flips >= 1, "至少 1 道 flip：向量贴字面，图谱沿本体/边命中权威页"
    print("  → Local 多跳沿边+本体落地，补上向量「语义像但关系断」的洞")


def demo_global(g: KnowledgeGraph, vs: VectorStore) -> None:
    section("3) Global 社区检索：主题级问题")
    q = "人事相关制度整体有哪些要点"
    comm = global_community_retrieve(g, q, top_k=1)[0]
    score, cid, summary = comm
    docs = sorted(g.community_docs.get(cid, set()) - {"noise-faq.md"})
    v_top = vs.retrieve(q, top_k=1)[0][1]
    print(f"Q: {q}")
    print(f"  community: {cid}  score={score:.3f}")
    print(f"  summary: {summary}")
    print(f"  community docs: {docs}")
    print(f"  vector top1: {v_top}")
    assert cid == "community-hr", "人事主题应命中 community-hr"
    assert "hr-leave.md" in docs, "人事社区应包含 hr-leave.md"
    print("  → Global 用社区摘要回答主题问，避免只贴到单句局部")


def demo_complement(g: KnowledgeGraph, vs: VectorStore) -> None:
    section("4) 互补边界：字面专名题向量已够，图谱不抢功")
    q = "X-KEY-99"
    v_docs = [d for _s, d in vs.retrieve(q, top_k=1)]
    g_docs = graph_retrieve_docs(g, q, top_k=1)
    print(f"Q: {q}")
    print(f"  vector top1={v_docs[0] if v_docs else None}")
    print(f"  graph  top1={g_docs[0] if g_docs else None}")
    assert v_docs and v_docs[0] == "it-security.md", "专名题向量应直接命中"
    assert g_docs and g_docs[0] == "it-security.md", "图谱也不应漂"
    print("  → 字面清晰时向量够用；图谱的 ROI 在多跳/主题，不在每题强行上")


def main() -> None:
    print("GraphRAG L6 demo (stdlib only: extract / local multihop / global community)")
    g = build_graph(CORPUS)
    vs = VectorStore()
    vs.build(CORPUS)
    demo_extract(g)
    demo_local_vs_vector(g, vs)
    demo_global(g, vs)
    demo_complement(g, vs)
    section("DONE · L6 GraphRAG green")
    print("pipeline: extract entities/rels → graph → local multihop | global community → 喂 LLM")
    print("vs vector: 向量找「像」的块；图谱找「连」的实体与社区")


if __name__ == "__main__":
    main()
