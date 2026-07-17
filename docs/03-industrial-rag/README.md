# 模块 03 · 工业级 RAG 核心技术

> 预计 25h ｜ 对应学习方案第三阶段 ｜ 支撑项目 P1

## 学习目标

从企业方案分层往上搭，每一层都自己写一遍。目标是理解**为什么 Naive RAG 在生产里不够用**，以及 Hybrid / Rerank / Query Rewrite / GraphRAG 各自解决什么问题。

## 分层知识地图

```
L1 Naive RAG   PDF → Chunk → Embedding → 向量库 → Retrieve → Prompt → LLM
      │
L2 Hybrid      BM25(关键词) + Vector(语义) → RRF 融合
      │
L3 Rerank      粗召回 → CrossEncoder / BGE-Reranker 精排
      │
L4 Query 优化  Query Rewrite / HyDE / Multi-Query / Self-Query
      │
L5 上下文工程  Parent-Child / Context Compression / Long Context
      │
L6 GraphRAG    实体+关系抽取 → Neo4j → Community → 图谱增强检索
```

## 核心概念清单

### L1 Naive RAG
- 文档加载（PDF/Markdown/Word）与清洗
- Chunk 策略：固定长度、滑动窗口、语义切分、按结构切分
- Embedding 模型选型（BGE / Qwen Embedding）
- 向量库：Milvus / pgvector 的选型与索引（HNSW/IVF）

### L2 Hybrid Search
- BM25 原理，稀疏 vs 稠密检索
- 为什么单靠向量会漏关键词
- RRF（Reciprocal Rank Fusion）融合排序

### L3 Rerank
- 召回-精排两段式架构，为什么需要精排
- Bi-Encoder vs Cross-Encoder
- BGE-Reranker 的用法与延迟权衡

### L4 Query 优化
- Query Rewrite：改写用户口语化提问
- HyDE：先生成假想答案再检索
- Multi-Query：一问多改写扩大召回
- Self-Query：从问题里抽结构化过滤条件

### L5 上下文工程
- Parent-Child Retrieval：小块检索、大块喂给模型
- Context Compression：压缩无关内容
- 长上下文的取舍与"迷失在中间"问题

### L6 GraphRAG
- 实体识别、关系抽取
- Neo4j 建图、Community 检测
- 图谱增强检索 vs 向量检索的互补

## 建议产出物

- [x] 跑通 L1 全链路的最小 RAG（`experiments/naive-rag/`，笔记 `naive-rag.md`；P1 M1 起点）
- [x] Hybrid 检索质量对比实验（`experiments/rag-hybrid-vs-naive/`，笔记 `hybrid-search.md`）
- [x] 同一问题在 Vector / BM25 / Hybrid 下的 hit@k 对比记录（见 hybrid demo 第 4 段）
- [x] Hybrid + Rerank 排序对照（`experiments/rag-rerank/`，笔记 `rerank.md`；MRR/Top-1 翻盘）
- [x] Query 优化四路对照（`experiments/rag-query-opt/`，笔记 `query-optimization.md`；Rewrite/HyDE/Multi/Self，MRR 0.458→1.000）
- [x] 上下文工程三抓手（`experiments/rag-context-eng/`，笔记 `context-engineering.md`；Parent-Child / Compression / Lost-in-middle）
- [x] GraphRAG 对照（`experiments/rag-graphrag/`，笔记 `graphrag.md`；抽取 / Local 多跳 / Global 社区，Graph 3/3 vs Vector 2/3 + 1 flip）

## 面试高频题（出口自测）

1. Naive RAG 在生产里主要有哪些问题？
2. Chunk 太大 / 太小分别有什么问题？怎么权衡？
3. 为什么要 Hybrid Search？BM25 和向量各擅长什么？
4. Rerank 为什么用 Cross-Encoder 而不是直接检索？代价是什么？
5. HyDE 的原理？什么场景下有用？
6. Parent-Child Retrieval 解决什么问题？
7. "Lost in the middle" 是什么？怎么缓解？
8. 什么场景该上 GraphRAG 而不是普通向量检索？

## 资源

- 各向量库官方文档（Milvus / pgvector）
- BGE / BGE-Reranker 模型卡与论文
- HyDE、GraphRAG（微软）原始资料
- RRF 融合相关资料

## 检查清单

- [x] 能画出六层 RAG 架构并说清每层解决的问题（L1/L2 笔记 + 本 README 地图）
- [x] 手写跑通 L1（`experiments/naive-rag/naive_rag.py`）
- [x] 手写跑通 L2 Hybrid（`experiments/rag-hybrid-vs-naive/hybrid_search.py`）
- [x] 手写跑通 L3 Rerank（`experiments/rag-rerank/rerank_demo.py`）
- [x] 手写跑通 L4 Query 优化（`experiments/rag-query-opt/query_opt_demo.py`）
- [x] 手写跑通 L5 上下文工程（`experiments/rag-context-eng/context_eng_demo.py`）
- [x] 手写跑通 L6 GraphRAG（`experiments/rag-graphrag/graphrag_demo.py`）
- [x] 能回答上面全部面试题（L1–L6 笔记 + 实验均可对照）
