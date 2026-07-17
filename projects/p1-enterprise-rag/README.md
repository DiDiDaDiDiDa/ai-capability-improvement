# P1 · 企业级 RAG 平台

> 预计 20h ｜ 串联模块 01 / 02 / 03 / 06

## 目标

构建一个**可落地**的知识库系统，而不是简单 Demo。文档进来能被切分、向量化、混合检索、精排，最后交给 LLM 生成带来源的答案。

## 能力清单

- [x] 文档导入：Markdown/TXT 最小加载（`p1rag/ingest.py`；PDF/Word 待扩展）
- [x] Chunk 切分策略：固定长度 + 重叠（L1）；Parent-Child（`experiments/rag-context-eng/`；语义切分待后续）
- [x] Embedding：可插拔接口 + 教学用 n-gram；BGE/Qwen 待换真模型
- [x] 向量存储：内存暴力库（L1）；pgvector / Milvus 待规模化
- [x] Hybrid Search：BM25 + Vector（RRF 融合；`p1rag/retrieve.py` + `experiments/rag-hybrid-vs-naive/`）
- [x] Reranker：教学版 Cross 交互精排（`experiments/rag-rerank/`；真 BGE-Reranker 可热替换 scorer）
- [x] Query Rewrite：改写用户提问（`experiments/rag-query-opt/`；Rewrite/HyDE/Multi/Self 四路，真 LLM 改写可热替换规则）
- [x] Prompt 模板管理（`prompts/rag-grounded.v1.md` + `p1rag/prompt.py`；Registry 复用模块 02）
- [x] 与 Gateway（P2）集成：`LLMProvider` 抽象 + Mock / HTTP OpenAI 兼容（`p1rag/gateway.py`）
- [x] 答案带来源引用（可溯源，`[S#]` + doc#chunk）

## 可运行入口（M4）

```bash
cd projects/p1-enterprise-rag
python3 app.py
# 默认 MockGatewayProvider，离线全绿

# 接真 Gateway / OpenAI 兼容端点：
P1_PROVIDER=http \
P1_GATEWAY_URL=http://127.0.0.1:8080/v1/chat/completions \
P1_GATEWAY_KEY=sk-... \
P1_GATEWAY_MODEL=gpt-4o-mini \
python3 app.py
```

```
data/*.md|*.txt
     │
p1rag.ingest   多格式加载
     │
p1rag.retrieve Hybrid(BM25+Vector+RRF)
     │
p1rag.prompt   rag-grounded.v1 + citations
     │
p1rag.gateway  Mock | HTTP → (P2 Gateway)
     │
answer + [S#] 来源
```

| 包模块 | 职责 |
|--------|------|
| `p1rag/ingest.py` | 扫目录导入 `.md`/`.txt` |
| `p1rag/retrieve.py` | Hybrid 索引与检索 |
| `p1rag/prompt.py` | 加载 grounded 模板、校验引用钩子 |
| `p1rag/gateway.py` | `LLMProvider`：`mock` / `http` 热替换 |
| `p1rag/pipeline.py` | 端到端 `ask()` |
| `app.py` | 验收脚本（4 题 hit@3 + 引用 + provider 抽象） |

## 目标架构

```
企业知识库
     │
Document Pipeline（加载 / 清洗 / Chunk）
     │
   Embedding
     │
   向量库（内存 → pgvector / Milvus）
     │
Hybrid Retrieval（BM25 + Vector）
     │
   Rerank（可选，实验见 modules）
     │
Prompt 组装（rag-grounded.v1 + 来源）
     │
   LLM（经 Gateway Provider）
     │
带引用的答案
```

## 建议里程碑

1. **M1 跑通 Naive RAG**：单一文档 → chunk → embedding → 检索 → 生成（`experiments/naive-rag/`）
2. **M2 加 Hybrid + Rerank**：召回质量对比实验（`experiments/rag-hybrid-vs-naive/`、`rag-rerank/`）
3. **M3 加 Query Rewrite + Parent-Child**：提升复杂问题效果（教学版实验可热替换）
4. **M4 工程化**：多格式导入、Prompt 模板、来源引用、Provider 接 Gateway（本目录 `app.py` ✅）

## 技术选型（建议，可换）

- 语言：Python（本仓库教学实现）或 Go（贴合 Gateway 技术栈）
- 向量库：内存 → pgvector → Milvus
- Embedding / Rerank：BGE 系列
- LLM 出口：P2 AI Gateway（OpenAI 兼容 `/v1/chat/completions`）

## 验收标准

- [x] 能导入一批真实文档并问答（`data/` 四篇制度 + FAQ）
- [x] Hybrid 相比纯字面有可运行链路（hit@3 四题全中）
- [x] 答案能给出来源（`citations` + 答案内 `[S#]`）
- [x] Provider 可热替换（`mock` 离线 / `http` 接 Gateway）

## 与 P2 的接缝

P1 **不实现** Router/Cache/熔断——那些是 P2 的活。P1 只认 `LLMProvider.chat(messages)`：

| 环境变量 | 含义 |
|----------|------|
| `P1_PROVIDER` | `mock`（默认）或 `http` |
| `P1_GATEWAY_URL` | Chat Completions 完整 URL |
| `P1_GATEWAY_KEY` | Bearer Token |
| `P1_GATEWAY_MODEL` | 模型名 |

P2 里程碑推进后，把 URL 指过去即可，无需改检索/Prompt 代码。
