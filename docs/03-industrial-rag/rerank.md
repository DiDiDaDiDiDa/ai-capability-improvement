# Rerank 精排（L3）

> 所属模块：03 · 工业级 RAG ｜ 学习日期：2026-07-16

## 一句话总结

Rerank = 在 **粗召回（Hybrid Top-N）** 之后，用更贵、更准的 **Cross-Encoder** 对「查询–文档对」逐对打分并重排；解决 Hybrid 已召回但 **排序噪声大、Top-1 不稳** 的问题——**召不回的救不了，排不准则浪费上下文窗口**。

## 我的理解

```
query q
   │
   ▼
L2 Hybrid 粗召回  ──►  候选 C = {d1..dN}   （N 常见 20~100）
   │
   ▼
L3 Rerank         ──►  score(q, di) 逐对精算  →  截断 Top-K（K 常见 3~10）
   │
   ▼
Grounded Prompt / LLM
```

### 1. 为什么 Hybrid 之后还要精排？

| 阶段 | 目标 KPI | 典型算法 | 成本形态 |
| ---- | -------- | -------- | -------- |
| 粗召回 L1/L2 | **Recall@N**（别漏） | BM25、向量 ANN、RRF | 对全库一次，便宜可扩展 |
| 精排 L3 | **nDCG / MRR / Top-1** | Cross-Encoder、BGE-Reranker | 只对 N 条，贵但 N 小 |

**底层逻辑**：召回要「网大」，排序要「刀快」。用 Cross-Encoder 扫全库不现实；用 Bi-Encoder 硬当最终排序，细粒度交互不够。

### 2. Bi-Encoder vs Cross-Encoder

| | Bi-Encoder（双塔） | Cross-Encoder（交叉） |
| -- | ----------------- | -------------------- |
| 输入 | 各自编码 `E(q)`、`E(d)` | 拼在一起 `E([q;d])` |
| 交互 | 编码后才比（点积/cosine） | **词级/层内全交互** |
| 索引 | 文档可预计算、ANN | **不能**离线成向量库检索 |
| 延迟 | 低（1 次 query 编码 + 检索） | 高（每个候选一次前向） |
| 精度 | 粗相关 | 细相关（否定、限定、数字） |

```
Bi:   [CLS] q ... → vq          [CLS] d ... → vd     → cos(vq, vd)
Cross:[CLS] q ... [SEP] d ... → 相关性 logit / 分数
```

**抓手**：生产默认 **双塔召回 + 交叉精排**（BGE 系常见组合：`bge-m3` / 向量 + `bge-reranker`）。

### 3. 精排模型在工程里长什么样

- **输入**：`(query, passage)` 对；中文常用 BGE-Reranker、Jina、Cohere Rerank API
- **输出**：标量相关性分；对候选 **argsort 降序**，再截 Top-K
- **截断纪律**：`N` 太大延迟炸；`K` 太大 prompt 噪声与费用升——先定延迟预算再定 N
- **过滤**：权限/租户/时间在召回侧下推；精排不要做「第一次权限检查」

### 4. 延迟与吞吐权衡（面试必答）

设粗召回返回 N，单次 Cross 前向耗时 t：

\[
T_{\text{rerank}} \approx N \cdot t \quad (\text{可 batch 摊薄，但下界仍随 } N \text{ 涨})
\]

| 旋钮 | 调大 | 调小 |
| ---- | ---- | ---- |
| N（进精排条数） | 召回更全、更慢更贵 | 快，但 gold 可能被截掉 |
| K（进 prompt 条数） | 证据多 | Lost in the Middle / 费 token |
| 模型大小 | 更准 | 延迟与 GPU 占用升 |
| batch size | 吞吐升 | 显存升 |

**铁律**：Rerank **不能**补偿「N 里没有 gold」——那是 L2 Recall 的锅。

### 5. 和 L2 / L4 的边界

| 层 | 解决 | 不解决 |
| -- | ---- | ------ |
| L2 Hybrid | 专名+语义漏召回 | Top-K 内排序噪声 |
| **L3 Rerank** | 候选内精细排序 | query 本身写得很烂 |
| L4 Query 优化 | 口语/残缺 query | 已召回集合的相对序 |

### 6. 教学版 vs 生产版

| | 本层实验 | 生产 |
| -- | -------- | ---- |
| Cross 打分 | 可解释的 **交互特征**（共现、覆盖率、专名命中、否定词等） | 真 Cross-Encoder / BGE-Reranker |
| 目的 | 看清「联合打分能重排」的结构 | 线上精度 |
| 接口 | `rerank(query, candidates) -> ordered` | 同构，可热替换 scorer |

## 核心要点

- 两段式：**粗召回保 Recall，精排保排序**
- Cross-Encoder 看 **(q,d) 对**，Bi-Encoder 看 **分离向量**
- 精排复杂度 ≈ **O(N)** 次模型前向，N 要受延迟预算约束
- 评测看 **Top-1 / MRR@K / nDCG**，不要只报 hit@K（那是召回指标）
- 换真模型只换 `score(q,d)`，管线：`retrieve_N → rerank → top_K → grounded`

## 动手记录

`experiments/rag-rerank/rerank_demo.py`：

1. **复用 L2 管线** 产出 Hybrid Top-N 候选
2. **教学 Cross 打分**：query–doc 交互特征（非双塔点积）
3. **重排对照**：至少 1 案 Top-1 从噪声变为 gold
4. **MRR 表**：粗排 vs 精排
5. **延迟模型**：打印「等价 N 次 pair score」成本提示
6. **救不回演示**：gold 不在候选时 rerank 无效（钉死边界）

## 踩过的坑 / 易混淆点

- **把 Rerank 当检索**：没有 ANN/倒排，全库 cross 会爆
- **N=K**：精排没有「重排空间」，等于白加延迟
- **只看 hit@K 宣称精排有效**：hit@K 在 rerank 前后不变（同一候选集）；要看 **序**
- **分数不可跨 query 比阈值**：不同 query 的绝对分分布不同，截断用 **排序位** 而非全局阈值（除非校准过）
- **中文长度**：passage 过长要截断策略（头尾/中心），否则模型吃不满或截断丢关键句

## 面试问答（自测）

- Q: 为什么 Rerank 用 Cross-Encoder 而不是继续用向量分？
  A: 交叉编码能做 token 级交互，对限定词、否定、数字更敏感；双塔为可索引牺牲了交互。
- Q: 代价是什么？
  A: 每个候选一次前向，延迟与 N 近似线性；不能预计算进 ANN。
- Q: N 和 K 怎么选？
  A: N 由延迟预算与召回曲线定（常见 20~50）；K 由上下文窗口与噪声敏感度定（常见 3~8）。
- Q: Rerank 能 ing 解决漏召回吗？
  A: 不能。gold 不在候选集就排不上来——先加 Hybrid / 放大 N / Query 改写。
- Q: 和 LLM 当 reranker 比？
  A: LLM listwise 可做但贵、慢、不稳；专用 reranker 延迟与成本更可控，生产优先。

## 参考资料

- 模块内：`hybrid-search.md`（L2 粗召回与 RRF）
- 模块内：`naive-rag.md`（Grounded 组装）
- 实验：`experiments/rag-rerank/rerank_demo.py`
- 项目：`projects/p1-enterprise-rag/README.md` M2
- BGE-Reranker 模型卡；Cross-Encoder 经典用法（sentence-transformers）
