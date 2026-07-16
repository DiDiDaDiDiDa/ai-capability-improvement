# Hybrid Search（L2）

> 所属模块：03 · 工业级 RAG ｜ 学习日期：2026-07-16

## 一句话总结

Hybrid Search = **稀疏通道（BM25 关键词）** + **稠密通道（向量语义）** 各自召回，再用 **RRF（倒数排名融合）** 合成统一排序；解决 Naive 只靠向量时「专有名词 / 编号 / 强字面」漏召回的问题。

## 我的理解

```
query q
   │
   ├──────────────┬────────────────┐
   ▼              ▼                │
BM25 Top-K_s   Vector Top-K_d      │  两路独立排序
(稀疏分数)      (cosine/点积)        │
   │              │                │
   └──────┬───────┘                │
          ▼                        │
     RRF 融合（按排名，不按原始分）  │
          ▼                        │
   Hybrid Top-K  →  (L3 Rerank) → Grounded Prompt
```

### 1. 稀疏 vs 稠密：各擅长什么

| 通道 | 表示 | 强项 | 弱项 |
| ---- | ---- | ---- | ---- |
| 稀疏 BM25 | 词项 TF-IDF 变体 | 专有名词、订单号、型号、法规条文号、用户原词 | 同义改写、口语 paraphrasing |
| 稠密 Vector | 连续向量 | 语义相近、说法不同、短句意图 | 稀有 ID、精确数字、OOV 专名 |

**底层逻辑**：不是「向量更高级所以取代关键词」，而是**两路互补**。生产里漏一个 SKU 号比语义差点更致命。

### 2. BM25 抓手（工程最小集）

对文档 \(d\)、查询词 \(t\)：

\[
\text{score}(d,q)=\sum_{t\in q}\text{IDF}(t)\cdot\frac{f(t,d)\cdot(k_1+1)}{f(t,d)+k_1\cdot(1-b+b\cdot|d|/\text{avgdl})}
\]

- \(k_1\)（常见 1.2~1.5）：词频饱和，防长文刷词
- \(b\)（常见 0.75）：文档长度归一
- \(\text{IDF}\)：稀有词权重大——「VPN」「拒报」比「员工」更有区分度

中文分词教学简化：**英文/数字整词 + 汉字 bigram** 当 term，不引入 jieba 也能演示 IDF 效应。

### 3. 为什么融合用 RRF，而不是把分数加起来？

| 做法 | 问题 |
| ---- | ---- |
| 直接加 BM25 分 + cosine | 量纲不同、分布不同，权重难调、换模型就漂 |
| min-max 归一再加权 | 可做，但对 Top-K 截断敏感，要调 α |
| **RRF** | 只看**排名**，\( \sum_i 1/(k+r_i) \)，跨系统稳定 |

RRF（Reciprocal Rank Fusion）经典形式：

\[
\text{RRF}(d)=\sum_{s\in\text{systems}}\frac{1}{k+r_s(d)}
\]

- \(r_s(d)\)：文档在系统 \(s\) 中的排名（从 1 起）；未进该路 Top-K 则不贡献或视作很大 rank
- \(k\) 常用 **60**（论文默认）；教学对比也可试 10/60

**抓手**：先 RRF 无脑融合拿到稳定收益，再谈学习融合权重 / 学排。

### 4. 和 L1 / L3 的边界

| 层 | 解决什么 | 不解决什么 |
| -- | -------- | ---------- |
| L1 Naive | 链路通、有引用 | 单通道漏召回 |
| **L2 Hybrid** | 关键词+语义互补 | Top-K 里噪声仍多、排序仍粗 |
| L3 Rerank（见 `rerank.md`） | 精排相关性 | 召回阶段就没进来的文档救不回 |

**铁律**：Rerank 只能重排「已经召回的」——Hybrid 的 KPI 是 **Recall@K**，Rerank 的 KPI 是 **nDCG / MRR**。

### 5. 生产落地注意

- **两路 Top-K 先放大再融合**（如各取 20 → RRF → 截 5 给 Rerank），避免一路截太狠
- 稀疏索引：Elasticsearch / OpenSearch / Tantivy；稠密：pgvector / Milvus
- 过滤（租户、权限、时间）在**两路检索前**统一下推，别融完再滤导致空结果
- 评测集要同时覆盖：**精确 ID 题** + **同义改写题**，只测一种会选错架构

## 核心要点

- Hybrid = BM25 + Vector + 融合（优先 RRF）
- 稀疏抓**字面与稀有词**，稠密抓**语义改写**
- **不要比绝对分**，比排名再融合
- 融合前两路 K 放大；融合后交给 L3 精排
- 本层实验纯标准库：手写 BM25 + n-gram 向量 + RRF，对照 Naive 的 hit@k

## 动手记录

`experiments/rag-hybrid-vs-naive/hybrid_search.py`：

1. **同语料三路检索**：Vector-only / BM25-only / Hybrid(RRF)
2. **精确词案**：查询含稀有专名 `X-KEY-99` → BM25 与 Hybrid 命中 IT 块，纯向量易漂
3. **改写案**：口语问住宿报销 → 向量/Hybrid 稳，弱分词 BM25 可能掉位
4. **RRF 表**：打印各 chunk 在两路的 rank 与 RRF 分，看融合如何「拉一把」
5. **小金标 hit@k**：多 query 汇总，Hybrid ≥ 单路（教学语料上可复现）

## 踩过的坑 / 易混淆点

- **「向量已经包含词信息了」**：近似语义 ≠ 保证精确 term；ID/编码仍要稀疏通道
- **分数加权调参上瘾**：先 RRF 拿基线，再考虑 α·dense+(1-α)·sparse
- **中文不切词直接按空格**：几乎全句一个 term，BM25 废掉；至少 bigram/分词
- **只融合 doc 不融合 chunk**：chunk 级 ID 要对齐，否则 RRF 对不上同一证据粒度
- **k=60 不是魔法**：候选很少时（K<10）可减小 k 让 rank 差更敏感

## 面试问答（自测）

- Q: 为什么要 Hybrid Search？
  A: 向量擅长语义，BM25 擅长精确词；企业问答里订单号/专名漏召回不可接受，两路互补再融合。
- Q: BM25 和 TF-IDF 差在哪？
  A: BM25 有词频饱和（k1）和长度归一（b），长文档刷词不会无限加分。
- Q: 为什么 RRF 比直接加分香？
  A: 跨系统量纲不一致；RRF 只依赖排名，换模型/调参更稳。
- Q: Hybrid 之后还要不要 Rerank？
  A: 要。Hybrid 提 Recall；Cross-Encoder 精排提排序质量。召不回的 Rerank 救不了。
- Q: RRF 的 k 是什么？
  A: 平滑常数，降低 rank=1 与 rank=2 的分差极端化，经典取 60。

## 参考资料

- 模块内：`naive-rag.md`（L1 全链路与缺陷地图）
- 模块内：`docs/01-nlp-dl-foundations/embedding.md`（稠密检索）
- 实验：`experiments/rag-hybrid-vs-naive/hybrid_search.py`
- 项目：`projects/p1-enterprise-rag/README.md` M2
- Cormack et al., Reciprocal Rank Fusion（RRF）
