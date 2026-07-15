# Naive RAG 全链路（L1）

> 所属模块：03 · 工业级 RAG ｜ 学习日期：2026-07-15

## 一句话总结

Naive RAG = **离线入库**（加载→清洗→切分→向量化→存库）+ **在线问答**（query 编码→Top-K 检索→拼 prompt→LLM），答案必须**带来源**；它能跑通，但在关键词漏召回、切分过碎/过粗、上下文塞满噪声时会系统性翻车——后面五层都是在补这些洞。

## 我的理解

```
离线（Ingest）                         在线（Query）
┌─────────────────────┐               ┌──────────────────────┐
│ 文档 PDF/MD/TXT     │               │ 用户问题 q           │
│   ↓ load + clean    │               │   ↓ embed(q)         │
│ 纯文本              │               │ 查询向量             │
│   ↓ chunk           │               │   ↓ ANN / brute topk │
│ Chunks[c_i]         │               │ 相关 chunks          │
│   ↓ embed           │               │   ↓ prompt 组装      │
│ Vectors[v_i] + meta │  向量库/索引  │ grounded messages    │
│   └──── store ──────┼──────────────▶│   ↓ LLM              │
└─────────────────────┘               │ 答案 + 引用 [src]    │
                                      └──────────────────────┘
```

Day2 的 `mini-semantic-search` 只做了「embed + cosine 找最近」。L1 把**切分、元数据、引用拼装**补齐，才叫 RAG 而不是「相似句搜索」。

### 1. 为什么要 Chunk？

| 不做 / 做坏 | 后果 |
|-------------|------|
| 整篇塞进 prompt | 超上下文、噪声大、贵、Lost in the Middle |
| 切得太碎（几十字） | 语义不完整，向量「看不全」，召回碎片 |
| 切得太粗（几千字） | 命中后塞进 prompt 仍噪声多，引用粒度差 |
| 无重叠 | 句子被拦腰切断，边界附近的问答丢召回 |

工程默认抓手：**固定长度 + 滑动重叠**（如 400 字、重叠 80）。结构切分（按标题/段落）和语义切分是 L5 再精细化。

### 2. 向量库在 Naive 阶段是什么？

Naive 里「向量库」可以是：
- 内存列表 `[(id, vec, text, meta), ...]` + 暴力 cosine（教学够用）
- 再往后才是 pgvector / Milvus + HNSW

**元数据必须一起存**：`doc_id / chunk_id / source_path / char_range`。没有 meta，就做不了「答案带来源」。

### 3. Grounded Prompt（有根的提示）

检索结果不是给用户看的，是给模型当**证据**的。模板纪律（复用模块 02）：

1. **instructions 与 data 分区**（XML / 明确标签）
2. 每条证据带 **可引用 ID**（`[S1]` `doc#chunk`）
3. 强制：**只依据证据作答；证据不足就说不知道；答案末尾列引用**
4. 用户问题放在证据之后或固定槽位，避免指令被 query 覆盖

```
system: 你只能依据 <evidence> 回答；不足则说不知道；引用 [S#]
user:
  <evidence>
  [S1] (policy.md#0) ...
  [S2] (policy.md#2) ...
  </evidence>
  <question>...</question>
```

### 4. Naive RAG 在生产里为什么不够？

| 痛点 | 现象 | 后面哪层补 |
|------|------|------------|
| 只靠稠密向量 | 专有名词/订单号漏召回 | L2 Hybrid（BM25） |
| Top-K 噪声多 | 相关度排序粗糙 | L3 Rerank |
| 用户问法口语/残缺 | 检索 query 质量差 | L4 Query 优化 |
| 小块召回、大块才够答 | 上下文不完整或过长 | L5 Parent-Child / 压缩 |
| 多跳关系 / 组织知识 | 纯段落向量够不着 | L6 GraphRAG |

**底层逻辑**：Naive 证明链路可通；工业级要的是**可控的召回质量与可溯源**。

## 核心要点

- 全链路五步：**Load → Chunk → Embed → Retrieve → Grounded Generate**
- Chunk 要带 **重叠 + 稳定 ID + 来源 meta**
- 检索默认 **归一化 + cosine / 点积**（Day2 结论）
- Prompt 必须 **证据分区 + 强制引用 + 拒答不足**
- 评测最小集：命中率（gold chunk 是否进 Top-K）、引用是否可回溯、拒答是否触发
- 本层实验用**可复现的哈希 n-gram 向量**演示结构；换 BGE 只换 embed 函数，管线不动（P1 M1）

## 动手记录

`experiments/naive-rag/naive_rag.py`（纯标准库）：

1. **切分**：`size=40, overlap=10` 时边界句可被相邻块同时覆盖；`overlap=0` 时拦腰切断
2. **入库**：3 篇假企业文档 → N 个 chunk，每条含 `doc_id/chunk_id/source`
3. **检索**：问「差旅住宿标准」命中差旅政策块；问「年假怎么算」命中人事块
4. **拼装**：输出带 `[S1][S2]` 的 grounded messages，`template_id=rag-grounded@v1`
5. **Naive 失败演示**：纯字面弱相关时，无 BM25 的稠密/n-gram 会漂——为 L2 留对照

## 踩过的坑 / 易混淆点

- **Chunk 大小单位**：按 token 估和按字符估差一截；中文粗算 1 字 ≈ 1~2 token，别直接抄英文 512 token 经验
- **Top-K 不是越大越好**：K 大召回升、噪声与费用也升；后面靠 Rerank 收
- **相似度分数不可跨模型比**：换 embedding 模型后绝对值漂移，看排序与业务指标
- **「检索到了」≠「模型用了」**：必须 grounded 指令 + 引用检查，否则模型会无视证据胡编
- **PDF 解析脏文本**：页眉页脚/分栏会污染 chunk；清洗是 ingest 一等公民，不是边角

## 面试问答（自测）

- Q: 画一下 Naive RAG 全链路？
  A: 离线 Load→Clean→Chunk→Embed→Store；在线 Embed(q)→TopK→拼 grounded prompt→LLM→带引用答案。
- Q: Chunk 太大/太小分别怎样？
  A: 太大噪声多、引用粗、易超窗；太小语义碎、向量漂、答案拼不起来。用长度+重叠折中，再按结构/语义升级。
- Q: 为什么答案必须带来源？
  A: 可审计、可纠错、抑制幻觉；企业场景「没出处的答案」业务上等于没答。
- Q: Naive 最大的生产问题？
  A: 单通道向量召回不稳、无精排、query 不改写、上下文工程缺失；需 Hybrid/Rerank/Query/Context 分层补齐。

## 参考资料

- 模块内：`docs/01-nlp-dl-foundations/embedding.md`（向量与 cosine）
- 模块内：`docs/02-prompt-engineering/structured-output.md`（分区与长上下文）
- 项目：`projects/p1-enterprise-rag/README.md` M1
- 实验：`experiments/naive-rag/naive_rag.py`
