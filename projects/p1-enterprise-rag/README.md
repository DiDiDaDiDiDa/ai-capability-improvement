# P1 · 企业级 RAG 平台

> 预计 20h ｜ 串联模块 01 / 02 / 03 / 06

## 目标

构建一个**可落地**的知识库系统，而不是简单 Demo。文档进来能被切分、向量化、混合检索、精排，最后交给 LLM 生成带来源的答案。

## 能力清单

- [ ] 文档导入：PDF / Markdown / Word
- [ ] Chunk 切分策略：固定长度 / 语义切分 / Parent-Child
- [ ] Embedding：BGE 或 Qwen Embedding
- [ ] 向量存储：Milvus 或 pgvector
- [ ] Hybrid Search：BM25 + Vector（RRF 融合）
- [ ] Reranker：BGE-Reranker 精排
- [ ] Query Rewrite：改写用户提问
- [ ] Prompt 模板管理（复用模块 02 的 Prompt SDK）
- [ ] 与 Gateway（P2）集成，通过统一 Provider 调用模型
- [ ] 答案带来源引用（可溯源）

## 目标架构

```
企业知识库
     │
Document Pipeline（加载 / 清洗 / Chunk）
     │
   Embedding
     │
   向量库（Milvus / pgvector）
     │
Hybrid Retrieval（BM25 + Vector）
     │
   Rerank（BGE-Reranker）
     │
Prompt 组装（含来源）
     │
   LLM（经 Gateway）
     │
带引用的答案
```

## 建议里程碑

1. **M1 跑通 Naive RAG**：单一 PDF → chunk → embedding → 检索 → 生成
2. **M2 加 Hybrid + Rerank**：召回质量对比实验
3. **M3 加 Query Rewrite + Parent-Child**：提升复杂问题效果
4. **M4 工程化**：多格式导入、Prompt 模板、来源引用、接 Gateway

## 技术选型（建议，可换）

- 语言：Python（生态成熟）或 Go（贴合你 Gateway 技术栈）
- 向量库：pgvector（起步简单）→ Milvus（规模化）
- Embedding / Rerank：BGE 系列

## 验收标准

- 能导入一批真实文档并问答
- Hybrid + Rerank 相比 Naive 有可量化的召回提升（记录在 `../../experiments/`）
- 答案能给出来源
