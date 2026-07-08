# 术语大图谱

一张"从底层到产品"的全景图，把仓库里所有高频术语挂到同一棵树上。看不懂某个词时，先回到这里定位它属于哪一层。

## 全景分层

```
                        ┌─────────────────────────────────────┐
产品层  Coding Agent /  │ Claude Code · Cursor · Aider · OpenHands
        Chat / RAG App  └───────────────┬─────────────────────┘
                                         │
编排层  Loop Engineering    gather → act → verify → repeat / 停止 / 反思
        Harness             system prompt · 工具集 · 编排 · 护栏 · 解析
                                         │
供给层  Context Engineering  窗口里装什么：提示+工具+检索+记忆+历史
        ├─ MCP              连接外部工具/数据（Tools/Resources/Prompts）
        ├─ Skills           打包流程与资源（渐进式披露）
        ├─ RAG              检索外部知识喂进窗口（模块 03）
        └─ Memory           短期/长期/向量记忆（模块 04）
                                         │
调用层  Prompt Engineering   单次调用措辞：Template/Few-shot/CoT/ReAct
        推理参数            Temperature/Top-P/Top-K/Stop（模块 01/02）
                                         │
模型层  LLM 本体            Transformer / Attention / KV Cache（模块 01）
                                         │
服务层  Serving             vLLM/SGLang · Batching · PagedAttention（模块 06）
        Gateway             Router/Cache/Fallback/Cost（模块 06）
```

## 按问题定位术语

| 你在纠结…            | 属于哪层        | 看哪              |
| ---------------- | ----------- | --------------- |
| 这句 prompt 怎么写    | 调用层         | 模块 02           |
| 窗口太长/装不下/该放什么    | 供给层 Context | 模块 00 / 03      |
| Agent 怎么接外部工具    | 供给层 MCP     | 模块 00 / 04      |
| 怎么把"做某类活"的流程复用   | 供给层 Skills  | 模块 00 / 04      |
| Agent 循环怎么停、怎么重试 | 编排层 Loop    | 模块 00 / 04 / P3 |
| 整个 agent 产品怎么搭   | 编排层 Harness | 模块 00 / P3      |
| 模型为什么这么算         | 模型层         | 模块 01           |
| 上线怎么扛并发/降成本      | 服务层         | 模块 06           |

## 一句话词典（速查）

- **Token / Embedding / Attention / KV Cache**：模型层，模块 01。
- **CoT / ToT / ReAct / Reflection / Few-shot**：推理与提示技术，模块 02。
- **RAG / Hybrid / Rerank / HyDE / GraphRAG**：检索增强，模块 03。
- **Memory / Planning / Tool Calling**：Agent 三要素，模块 04。
- **MCP**：连接层协议（Tools/Resources/Prompts），模块 00/04。
- **Skills / Progressive Disclosure**：流程打包 + 按需加载，模块 00/04。
- **Prompt / Context / Harness / Loop Engineering**：四层递进工程，模块 00。
- **LoRA / QLoRA / DPO / LLM-Judge**：微调与评估，模块 05。
- **vLLM / PagedAttention / Continuous Batching / Semantic Cache / Router**：服务化，模块 06。

## 记忆锚点

- **一条线**：文本 →(01 模型)→ 一句 prompt →(02 调用)→ 窗口内容 →(00/03 供给)→ 脚手架 →(00/P3 编排)→ 产品。
- **两组词**：MCP+Skills 是"喂什么"，四层 engineering 是"怎么围着模型做工程"。
- **越往上越值钱**：模型层大同小异，产品/编排层才是 AI Infra 岗位的差异化竞争力。
