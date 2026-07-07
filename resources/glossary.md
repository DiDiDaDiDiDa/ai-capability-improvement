# 术语表

学习过程中随手记录关键术语，按模块归类。用自己的话写，别抄定义。

## 模块 01 基础
- **Token**：模型处理文本的最小单位，通常是子词，不等于字/词。
- **BPE**：Byte Pair Encoding，基于高频字节对合并的子词分词算法。
- **Embedding**：把 token/文本映射为稠密向量以表示语义。
- **Self-Attention**：序列内每个位置对其他位置加权聚合的机制（QKV）。
- **KV Cache**：自回归解码时缓存历史 K、V，避免重复计算，加速推理。
- **RoPE**：旋转位置编码，相对位置信息注入注意力。
- **Temperature / Top-P / Top-K**：控制采样随机性的参数。

## 模块 02 提示词
- **CoT**：Chain-of-Thought，引导模型显式写出推理步骤。
- **ReAct**：Reasoning + Acting 交替，Agent 的基础循环。
- **Few-shot**：在 prompt 中给少量示例引导输出。

## 模块 03 RAG
- **Chunk**：文档切分后的片段。
- **BM25**：经典关键词检索算法（稀疏检索）。
- **RRF**：Reciprocal Rank Fusion，多路检索结果融合排序。
- **Rerank**：对粗召回结果用 Cross-Encoder 精排。
- **HyDE**：先让模型生成假想答案再拿去检索。
- **GraphRAG**：基于知识图谱增强的检索。

## 模块 00 关键概念（Agent 时代）
- **MCP**：Model Context Protocol，Anthropic 提出的开放协议，统一 AI 应用与工具/数据的连接（USB-C 类比）。三原语：Tools / Resources / Prompts。"连接层"。
- **Skills**：把做某类任务的流程与资源打包成文件夹（SKILL.md + 附件），渐进式披露按需加载。"知识/流程层"。
- **Progressive Disclosure**：渐进式披露，平时只加载 skill 名字+描述，用到才读全文，避免撑爆上下文。
- **Prompt Engineering**：优化单次调用的措辞。作用域=一条消息。
- **Context Engineering**：管理整个上下文窗口装什么（提示+工具+检索+记忆+历史），把上下文当有限资源经营。
- **Harness Engineering**：优化模型外的整个脚手架（系统提示/工具/编排/护栏/解析）。Claude Code、Cursor 即 harness。
- **Loop Engineering**：优化 Agent 循环控制流（迭代/停止/重试/反思/子 Agent）。
- 作用域递进：Prompt ⊂ Context ⊂ Harness ⊂ Loop。

## 模块 04 Agent
- **Memory**：短期/长期/向量记忆。
- **Planning**：任务分解与执行规划。
- **Tool Calling / Function Calling**：模型按 schema 调用外部工具。

## 模块 05 微调评估
- **LoRA / QLoRA**：参数高效微调方法。
- **SFT / DPO / RLHF**：不同的模型对齐/微调阶段。
- **LLM-as-Judge**：用大模型给输出打分的评估方式。

## 模块 06 AI Infra
- **Continuous Batching**：动态批处理，提升推理吞吐。
- **PagedAttention**：KV Cache 的分页显存管理（vLLM）。
- **Speculative Decoding**：小模型草稿 + 大模型验证加速。
- **Semantic Cache**：按语义相似度命中的缓存。
- **Circuit Breaker**：熔断，故障时快速失败保护系统。
