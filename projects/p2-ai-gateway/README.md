# P2 · AI Gateway 增强版

> 预计 15h ｜ 串联模块 02 / 06

## 目标

基于你现有的 Gateway 项目继续扩展（不重造轮子），补齐 AI Infra 岗位最看重的治理、路由、缓存、可观测能力。

## 能力清单

- [ ] Model Router：按成本 / 延迟 / 能力动态选模型
- [ ] Semantic Cache：语义相似命中，省调用
- [ ] Prompt Version 管理（复用模块 02）
- [ ] Token Cost Dashboard：成本可视化
- [ ] Guardrail：输入输出安全 / 敏感信息 Masking
- [ ] Fallback + Retry：Provider 故障兜底
- [ ] Circuit Breaker：熔断保护
- [ ] Rate Limit / Quota：限流与配额
- [ ] Observability：Tracing + Metrics

## 目标架构

```
Client
  │
  ▼
Gateway
  ├─ Router（成本/延迟/能力）
  ├─ Semantic Cache（命中直接返回）
  ├─ Prompt Compression / Version
  ├─ Guardrail / Masking
  ├─ Fallback / Retry / Circuit Breaker
  ├─ Rate Limit / Quota / Cost / Audit
  └─ Observability（Trace / Metrics）
  │
  ▼
Multi Provider（OpenAI / Anthropic / Gemini / Qwen / DeepSeek）
```

## 建议里程碑

1. **M1 Provider 抽象 + Fallback/Retry**：统一接口 + 可靠性
2. **M2 Model Router**：按规则/成本选模型
3. **M3 Semantic Cache**：embedding 相似度命中 + Redis
4. **M4 Cost & Observability**：成本核算 + Tracing + Dashboard
5. **M5 Guardrail**：输入输出安全

## 安全提示

Gateway 对外暴露，务必设计好鉴权与限流。新增任何对外端点时确认认证是否到位，不要留无鉴权入口。

## 与 P1 的接缝（已预留）

P1 企业级 RAG（`projects/p1-enterprise-rag/`）已通过 `LLMProvider` 抽象对接 OpenAI 兼容 Chat Completions：

```bash
# P1 侧把出口指到本 Gateway（P2 起服务后）：
P1_PROVIDER=http \
P1_GATEWAY_URL=http://127.0.0.1:<gateway-port>/v1/chat/completions \
P1_GATEWAY_KEY=<token> \
python3 projects/p1-enterprise-rag/app.py
```

P1 默认 `mock-gateway` 离线可跑；真链路验收 = P2 提供兼容端点 + 鉴权/限流。

## 验收标准

- 一个 Provider 挂了能自动 Fallback
- 相似请求能命中 Semantic Cache
- Dashboard 能看到 token 成本与延迟
- P1 能通过 `P1_PROVIDER=http` 经本 Gateway 完成一次 grounded 问答
