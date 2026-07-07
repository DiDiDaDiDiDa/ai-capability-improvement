# AI Capability Improvement

> 从 Token 到 Coding Agent —— 一份面向 AI Infra / LLM 应用工程的实战学习仓库。
> 理论够用即可，动手写代码为主，用项目倒逼补盲。

![topic](https://img.shields.io/badge/topic-LLM%20Engineering-blue)
![topic](https://img.shields.io/badge/focus-AI%20Infra-green)
![license](https://img.shields.io/github/license/DiDiDaDiDiDa/ai-capability-improvement)

面向 **AI Infra / LLM 应用工程** 方向的系统学习仓库，用于沉淀学习笔记、架构图、提示词模板、评测样例和实战项目。

目标不是"了解 AI 是什么"，而是能在工程一线动手做：把 Token、Embedding、Transformer、RAG、Agent、Serving、Gateway 这些天天要碰的东西讲清楚、写出来、跑起来。

---

## 六大知识模块

| # | 模块 | 目录 | 一句话 |
|---|------|------|--------|
| 00 | 关键概念速览 | [`docs/00-key-concepts`](docs/00-key-concepts/) | MCP、Skills、Prompt/Context/Harness/Loop Engineering |
| 01 | NLP 与深度学习基础 | [`docs/01-nlp-dl-foundations`](docs/01-nlp-dl-foundations/) | Token、Embedding、Transformer、KV Cache、采样 |
| 02 | 结构化提示词设计框架 | [`docs/02-prompt-engineering`](docs/02-prompt-engineering/) | Template、Few-shot、CoT/ToT、ReAct、结构化输出 |
| 03 | 工业级 RAG 核心技术 | [`docs/03-industrial-rag`](docs/03-industrial-rag/) | Hybrid Search、Rerank、Query Rewrite、GraphRAG |
| 04 | Agent 核心架构三要素 | [`docs/04-agent-architecture`](docs/04-agent-architecture/) | Memory、Planning、Tool、Workflow、多智能体 |
| 05 | 模型微调与量化评估 | [`docs/05-finetune-eval`](docs/05-finetune-eval/) | LoRA/QLoRA、SFT/DPO、BLEU/ROUGE、LLM Judge |
| 06 | AI Infra 与服务化 | [`docs/06-ai-infra`](docs/06-ai-infra/) | Serving、Gateway、Cache、Router、多 Provider |


## 实战项目（倒逼学习）

| # | 项目 | 目录 | 串联模块 |
|---|------|------|----------|
| P1 | 企业级 RAG 平台 | [`projects/p1-enterprise-rag`](projects/p1-enterprise-rag/) | 01 / 02 / 03 / 06 |
| P2 | AI Gateway 增强版 | [`projects/p2-ai-gateway`](projects/p2-ai-gateway/) | 02 / 06 |
| P3 | Mini Coding Agent | [`projects/p3-mini-coding-agent`](projects/p3-mini-coding-agent/) | 02 / 03 / 04 / 06 |

---

## 目录结构

```
.
├── README.md                # 本文件：总览与导航
├── LEARNING-PLAN.md         # 详细学习方案（分阶段 / 每日计划 / 检验标准）
├── docs/                    # 知识模块笔记
│   ├── 00-key-concepts/     # 关键概念速览（MCP / Skills / 四层 engineering）
│   ├── 01-nlp-dl-foundations/
│   ├── 02-prompt-engineering/
│   ├── 03-industrial-rag/
│   ├── 04-agent-architecture/
│   ├── 05-finetune-eval/
│   ├── 06-ai-infra/
│   └── _template.md         # 单篇笔记模板
├── projects/                # 三个实战项目
│   ├── p1-enterprise-rag/
│   ├── p2-ai-gateway/
│   └── p3-mini-coding-agent/
├── prompts/                 # 可复用提示词模板与版本记录
├── experiments/             # 实验设计、评测样例、运行结果
└── resources/               # 术语表、精选阅读清单
    ├── glossary.md
    └── reading-list.md
```

## 怎么用这个仓库

1. 先读 [`LEARNING-PLAN.md`](LEARNING-PLAN.md)，它是主干：阶段划分、时间分配、每日任务、检验标准。
2. 每个模块的 `README.md` 是该模块的**学习大纲**：学习目标、知识地图、核心概念、面试高频题、产出物、检查清单、资源。
3. 学习时按 [`docs/_template.md`](docs/_template.md) 在对应模块目录下新建单篇笔记（如 `01-nlp-dl-foundations/tokenization.md`）。
4. 提示词沉淀进 `prompts/`，实验和评测进 `experiments/`，术语随手记进 [`resources/glossary.md`](resources/glossary.md)。
5. 每个模块学完对照 README 末尾的检查清单自测，能讲清楚 + 能写出来 = 通过。

## 学习原则

- **能画图**：Transformer、RAG 链路、Agent 循环都要能默画出来。
- **能手写**：核心组件（Tokenizer、Retriever、Prompt Builder、Agent Loop）至少手写一个最小实现。
- **能回答**：每个模块的面试题当作出口检验，讲不清就是没学透。
- **项目倒逼**：知识模块和项目并行，用项目需求驱动补齐知识盲区。
