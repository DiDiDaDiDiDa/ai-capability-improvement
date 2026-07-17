# 详细学习方案（约 115h）

面向 AI Infra / LLM 应用工程方向的实战型学习计划。原则：**理论够用即可，动手写代码为主，用项目倒逼补盲。**

## 总体路线

```
第一阶段 基础 (20h)          第二阶段 提示词 (15h)
Token / Embedding             Template / Few-shot
Transformer / KV Cache        CoT / ToT / ReAct
采样 / 推理参数        ─┐      结构化输出 / Tool Call
                        │              │
                        ▼              ▼
第三阶段 RAG (25h)  ◀──────  第四阶段 Agent (20h)
Naive → Hybrid → Rerank       Memory / Planning / Tool
Query Rewrite / HyDE          Workflow / 多智能体
GraphRAG                              │
        │                             │
        ▼                             ▼
第五阶段 模型工程 (10h)       第六阶段 AI Infra (25h)
LoRA / QLoRA / DPO            Serving / vLLM / PagedAttn
BLEU / ROUGE / LLM Judge      Gateway / Cache / Router
                                      │
                                      ▼
                        贯穿三大实战项目（并行推进）
                        P1 企业级 RAG / P2 Gateway / P3 Coding Agent
```

## 时间分配表

| 阶段  | 模块          | 时间   | 核心产出                                  |
| --- | ----------- | ---- | ------------------------------------- |
| 一   | NLP 与深度学习基础 | 20h  | 理论笔记 + Transformer 架构图 + 手写 Tokenizer |
| 二   | 结构化提示词设计    | 15h  | Prompt SDK / 模板库                      |
| 三   | 工业级 RAG     | 25h  | 企业知识库 Demo（P1 起步）                     |
| 四   | Agent 架构    | 20h  | Mini Agent（P3 起步）                     |
| 五   | 微调与评估       | 10h  | LoRA 实验 + 评测脚本                        |
| 六   | AI Infra    | 25h  | Gateway 增强版（P2）+ Serving 笔记           |
| —   | 三大实战项目收尾    | 与上并行 | P1 / P2 / P3 可运行                      |

> 说明：知识模块和项目**不是先后关系而是并行**。学到 RAG 时就动手搭 P1，学到 Agent 时就动手搭 P3。项目里遇到的坑回头补对应模块。

---

## 第一阶段：NLP 与深度学习基础（20h）

对应模块 [`docs/01-nlp-dl-foundations`](docs/01-nlp-dl-foundations/)。基础不用学太深，但工程天天碰的这几样必须吃透。

### Day 1 — 分词 Tokenization（4h）
- 什么是 Token，为什么 Token ≠ 字/词
- BPE 原理、SentencePiece、WordPiece 区别
- 为什么 GPT 用 BPE，Qwen 的 tokenizer 有何不同
- **动手**：用 `tiktoken` / `transformers` 观察同一句话在不同模型下的分词结果；手写一个最小 BPE 训练+编码

### Day 2 — Embedding（4h）
- 向量为什么能表示语义，词向量 → 句向量的演进
- Cosine Similarity / L2 Distance / Dot Product 的区别与适用
- 为什么 Retrieval 用 Embedding
- **动手**：调用一个 embedding 模型，算两句话相似度，画一个二维可视化

### Day 3 — Transformer（8h，重点，必须画图）
- Self-Attention（QKV 怎么来、缩放点积怎么算）
- Multi-Head Attention、Residual、LayerNorm、FFN
- Encoder vs Decoder，为什么现在主流是 Decoder-only
- Position Encoding（绝对/RoPE）
- **KV Cache**：为什么需要、缓存了什么、和显存/吞吐的关系（面 Gateway 必问）
- **动手**：默画一张完整 Transformer 结构图；手写单头 self-attention

### Day 4 — 推理与采样（4h）
- Prefill / Decode 两阶段，自回归生成
- Temperature / Top-P / Top-K / 采样策略
- Stop、max_tokens、Tool Call、Structured Output
- **动手**：同一 prompt 调不同 temperature/top_p，观察输出分布变化

---

## 第二阶段：结构化提示词设计（15h）

对应模块 [`docs/02-prompt-engineering`](docs/02-prompt-engineering/)。跳过"你是一位…请一步步思考"这类过时写法，直接学工程化的 Prompt Platform。

- **Day 5（4h）**：Prompt Template、变量注入、Few-shot、System/User/Assistant 分层
- **Day 6（4h）**：CoT、Self-Consistency、Tree-of-Thought、Reflection、ReAct
- **Day 7（4h）**：结构化输出（JSON/XML Prompt）、Tool Calling Prompt、Long Context 组织
- **Day 8（3h）**：Prompt 工程化——版本管理、测试、评估（Prompt Registry / DSL 思路）
- **产出**：一个 Prompt SDK / Prompt Builder（Go Template 或 Python），支持模板、版本、few-shot 注入

---

## 第三阶段：工业级 RAG（25h）

对应模块 [`docs/03-industrial-rag`](docs/03-industrial-rag/)。从企业方案分层往上搭，每层都自己写。

- **L1 Naive RAG（4h）**：PDF → Chunk → Embedding → 向量库 → Retrieve → Prompt → LLM，跑通全链路
- **L2 Hybrid Search（4h）**：BM25 + Vector 融合，RRF 排序
- **L3 Rerank（4h）**：CrossEncoder / BGE-Reranker，召回-精排两段式
- **L4 Query 优化（5h）**：Query Rewrite、HyDE、Multi-Query、Self-Query
- **L5 上下文工程（4h）**：Parent-Child Retrieval、Context Compression、Long Context
- **L6 GraphRAG（4h）**：实体/关系抽取、Neo4j、Community、图谱增强检索
- **产出**：项目 P1 的核心检索链路可运行

---

## 第四阶段：Agent 架构（20h）

对应模块 [`docs/04-agent-architecture`](docs/04-agent-architecture/)。按 Agent = LLM + Memory + Planning + Tool + Observation + Reflection 展开。

- **Day（4h）**：Agent Loop 本质、ReAct 落地、Observation/Reflection
- **Memory（4h）**：Short/Long/Vector Memory，记忆写入与召回
- **Planning（4h）**：Task 分解、SubTask、执行、Retry
- **Tool（4h）**：JSON Schema、Function Calling、MCP、OpenAPI 工具
- **Workflow & 多智能体（4h）**：Sequential/Parallel/Router/Loop；Supervisor-Worker、Planner-Executor
- **产出**：Mini Agent（P3 起步）

---

## 第五阶段：模型微调与评估（10h）

对应模块 [`docs/05-finetune-eval`](docs/05-finetune-eval/)。AI Infra 岗位不用深入训练，但要能答清楚"何时微调、何时用 RAG、何时用 Prompt"。

- **微调（5h）**：LoRA / QLoRA / PEFT 原理，SFT / DPO / RLHF 流程概念，量化（INT8/INT4）
- **决策（含上）**：微调 vs RAG vs Prompt 的选型逻辑（面试高频）
- **评估（5h）**：BLEU / ROUGE / BERTScore，LLM-as-Judge、Arena、Prompt Evaluation
- **产出**：一次最小 LoRA 微调实验 + 一套评测脚本（进 `experiments/`）

---

## 第六阶段：AI Infra 与服务化（25h）

对应模块 [`docs/06-ai-infra`](docs/06-ai-infra/)。ChatGPT 说这块"反而最重要"，是岗位核心。

- **Serving（8h）**：vLLM / SGLang / Triton / LMDeploy；Continuous Batching、PagedAttention、KV Cache、Speculative Decoding
- **Gateway（8h）**：Provider 抽象、Router、Fallback、Retry、Circuit Breaker、Rate Limit、Quota、Cost、Audit
- **Cache（4h）**：KV Cache、Semantic Cache、Embedding Cache、Redis
- **Multi Provider & Cost（5h）**：OpenAI/Anthropic/Gemini/Qwen/DeepSeek 统一接口；Token Cost、Latency、Model Routing
- **产出**：项目 P2（Gateway 增强版）

---

## 三大实战项目（并行推进）

详见各项目目录，此处只列时间与定位。

| 项目                   | 时间   | 何时启动    | 目录                                                                |
| -------------------- | ---- | ------- | ----------------------------------------------------------------- |
| P1 企业级 RAG 平台        | ~20h | 学到第三阶段时 | [`projects/p1-enterprise-rag`](projects/p1-enterprise-rag/)       |
| P2 AI Gateway 增强版    | ~15h | 学到第六阶段时 | [`projects/p2-ai-gateway`](projects/p2-ai-gateway/)               |
| P3 Mini Coding Agent | ~25h | 学到第四阶段后 | [`projects/p3-mini-coding-agent`](projects/p3-mini-coding-agent/) |

---

## 学习方法与检验标准

- **每个知识点三问**：能画图吗？能手写最小实现吗？能回答模块 README 里的面试题吗？三个都能才算过。
- **笔记即产出**：用 [`docs/_template.md`](docs/_template.md) 记录，重点是"我怎么理解的"和"踩了什么坑"，不是抄定义。
- **每周复盘**：周末回顾本周笔记，把讲不清的点标红，下周优先补。
- **出口检验**：每个模块末尾有检查清单，全部打勾 = 该模块结束。
- **项目验收**：三个项目都能 `run` 起来、能演示核心链路，即达标。

## 进度追踪

建议在此维护一个简单进度表（学到哪算哪）：

| 模块 / 项目         | 状态    | 起止  | 备注  |
| --------------- | ----- | --- | --- |
| 00 关键概念        | ✅ 完成  | 2026-07-07 | MCP/Skills/四层工程 自测通过 |
| 01 基础           | ✅ 完成  | 2026-07-07 ~ 07-08 | 分词/Embedding/Transformer/推理采样，4篇笔记+4实验 |
| 02 提示词          | ✅ 完成  | 2026-07-14 | Day5~8 笔记+实验+模板库+Prompt Registry SDK |
| 03 RAG          | ✅ 完成  | 2026-07-15 ~ 07-17 | L1–L6 笔记+实验全绿（Hybrid/Rerank/Query/Context/GraphRAG） |
| 04 Agent        | ✅ 完成  | 2026-07-17 | Mini Agent 实验+双笔记；Loop/Memory/Plan/Tool/多Agent 全绿；P3 M1 起点 |
| 05 微调评估         | ⬜ 未开始 |     |     |
| 06 AI Infra     | ⬜ 未开始 |     |     |
| P1 RAG 平台       | ✅ 完成  | 2026-07-15 ~ 07-17 | M1–M4：`projects/p1-enterprise-rag/app.py` 可运行；Gateway Provider 可热替换 |
| P2 Gateway      | ⬜ 未开始 |     |     |
| P3 Coding Agent | ⬜ 未开始 |     |     |

状态标记：⬜ 未开始 / 🟡 进行中 / ✅ 完成
