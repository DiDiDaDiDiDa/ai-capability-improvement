# 模块 06 · AI Infra 与服务化

> 预计 25h ｜ 对应学习方案第六阶段 ｜ 支撑项目 P2

## 学习目标

这块是 AI Infra 岗位的核心竞争力，也和你手上的 Gateway 项目直接对接。掌握推理服务化、Gateway 各项能力、缓存与路由，能把前面所有模块串成一条生产链路。

## 全景链路

```
Client
  │
  ▼
AI Gateway ──▶ Router(按成本/延迟/能力选模型)
  │            Fallback / Retry / Circuit Breaker
  │            Rate Limit / Quota / Cost / Audit
  │            Semantic Cache / Prompt Compression / Guardrail
  ▼
Multi Provider（OpenAI / Anthropic / Gemini / Qwen / DeepSeek 统一接口）
  │
  ▼
Serving（vLLM / SGLang / Triton）
  Continuous Batching / PagedAttention / KV Cache / Speculative Decoding
```

## 核心概念清单

### 1. Serving（推理服务化）
- vLLM / SGLang / Triton / LMDeploy 的定位
- Continuous Batching：为什么能大幅提吞吐
- PagedAttention：KV Cache 的分页管理
- Speculative Decoding：小模型草稿 + 大模型验证
- 吞吐 vs 延迟 vs 显存的权衡

### 2. Gateway
- Provider 抽象层、统一接口
- Router：按成本 / 延迟 / 能力动态选模型
- 可靠性：Fallback、Retry、Circuit Breaker
- 治理：Rate Limit、Quota、Cost 核算、Audit 审计
- 安全：Guardrail 输入输出、敏感信息 Masking

### 3. Cache
- KV Cache（推理层）
- Semantic Cache（语义相似命中）
- Embedding Cache、Redis 落地
- 缓存的正确性与失效策略

### 4. Multi Provider & 成本
- 统一 OpenAI/Anthropic/Gemini/Qwen/DeepSeek 接口的抽象设计
- Token Cost、Latency 监控
- Model Routing 策略（贵模型兜底、便宜模型打头）

### 5. 可观测性
- Tracing、Metrics、日志
- 请求级成本与延迟归因

## 建议产出物

- [x] 一份 vLLM / PagedAttention 原理笔记 + 机制账（[`serving-batching-paged.md`](serving-batching-paged.md) + `experiments/ai-infra/serving_demo.py`）
- [ ] 项目 P2：Gateway 增强版（Router + Semantic Cache + Fallback + Cost Dashboard）
- [ ] 一个 Semantic Cache 最小实现（embedding 相似度命中）

## 笔记与实验

| 主题 | 笔记 | 实验断言要点 |
|------|------|----------------|
| Serving 四机制 | [`serving-batching-paged.md`](serving-batching-paged.md) | KV 162x；连续 batch 利用率 34%→87% 吞吐 2.57x；分页省 65% 显存；投机 3.70x |
| Gateway / Cache / Router | 落到项目 P2（进行中） | — |

```bash
python3 experiments/ai-infra/serving_demo.py
```

## 面试高频题（出口自测）

1. Continuous Batching 和静态 batching 的区别？为什么前者吞吐高？
2. PagedAttention 解决了什么问题？和操作系统分页的类比？
3. Speculative Decoding 的原理？什么时候收益大？
4. Gateway 的 Fallback 和 Circuit Breaker 分别处理什么场景？
5. Semantic Cache 怎么判断命中？可能出什么错？
6. 多 Provider 统一接口的难点在哪（能力差异、参数差异）？
7. 怎么做 Model Routing 才能兼顾成本和质量？
8. KV Cache 和 Semantic Cache 是一回事吗？

## 资源

- vLLM / SGLang 官方文档与论文（PagedAttention）
- 各 Provider API 文档
- 你自己的 Gateway 项目代码

## 检查清单

- [x] 能画出 Client → Gateway → Provider → Serving 全链路（见全景链路图）
- [x] 能讲清 Continuous Batching / PagedAttention / Speculative Decoding（笔记 + 实验全绿）
- [ ] 完成 P2 Gateway 增强版
- [ ] 能回答上面全部面试题（Serving 三题已覆盖，Gateway/Cache 随 P2 补齐）
