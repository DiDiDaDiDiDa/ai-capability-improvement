# P2 · AI Gateway 增强版

> 预计 15h ｜ 串联模块 02 / 06

## 目标

基于你现有的 Gateway 项目继续扩展（不重造轮子），补齐 AI Infra 岗位最看重的治理、路由、缓存、可观测能力。

## 能力清单

- [x] Model Router：按成本 / 延迟 / 能力动态选模型 — `p2gateway/router.py`（cost/latency/quality/balanced 四策略 + 能力硬过滤 + 无候选 RouteError；自身实现 P1 `chat` 契约可热插）｜实现详解见 [`model-router.md`](model-router.md)
- [x] Semantic Cache：语义相似命中，省调用 — `p2gateway/semantic_cache.py`（embedding+余弦阈值命中 + TTL 失效 + 容量淘汰 + 阈值防误命中；装饰器套 Router 外层）｜实现详解见 [`semantic-cache.md`](semantic-cache.md)
- [x] Prompt Version 管理（**应用层 SDK**，复用模块 02）— `p2gateway/prompt_client.py`（直接 import 模块02 `PromptRegistry`：版本钉扎 + alias 发布回滚 + A/B 稳定分桶 + 版本不可变）；**Gateway 只收不透明 `version_tag` 做归因，不碰 prompt 内容**｜分层详解见 [`prompt-version.md`](prompt-version.md)
- [x] Token Cost Dashboard：成本可视化 — `p2gateway/cost_dashboard.py`（`MeteredProvider` 最外层采集 + `CostTracker` 按 provider/version/cache 多维聚合 + `render_dashboard` 文本面板；量化「缓存省了多少钱」）｜实现详解见 [`cost-dashboard.md`](cost-dashboard.md)
- [x] Fallback + Retry：Provider 故障兜底 — `p2gateway/resilience.py`（`ResilientProvider`：瞬时错误指数退避重试 + 重试耗尽 Fallback 换候选 + RetryableError/FatalError 错误分类 + 全挂抛 AllProvidersFailed；回填 `usage.resilience`）｜实现详解见 [`fallback-retry.md`](fallback-retry.md)
- [x] Circuit Breaker：熔断保护 — `p2gateway/circuit_breaker.py`（`CircuitBreaker` closed→open→half-open 三态机 + 滑动窗口失败率跳闸 + 冷却半开探针恢复；每 Provider 一个 breaker，与 Fallback/Router 咬合）｜实现详解见 [`circuit-breaker.md`](circuit-breaker.md)
- [x] Guardrail：输入输出安全 / 敏感信息 Masking — `p2gateway/guardrail.py`（`GuardedProvider` 套最外层：输入注入 block + 输入/输出 PII 正则 mask + 命中回填 `usage.guardrail`；密钥整体遮蔽、联系方式保留局部）｜实现详解见 [`guardrail.md`](guardrail.md)
- [x] Rate Limit / Quota：限流与配额 — `p2gateway/rate_limit.py`（`RateLimitedProvider`：Token Bucket 限流 + Quota 预估占额/事后真实核销 + 按 key 多租户隔离；回填 `usage.limit` 余量）｜实现详解见 [`rate-limit-quota.md`](rate-limit-quota.md)
- [x] Observability：Tracing + Metrics — `p2gateway/observability.py`（`TracedProvider` 每层开 span 共享 trace_id + `MetricsRegistry` 计数/分位数延迟 p50/p95/p99 + 复用 usage 做 labels；回填 `usage.trace`）｜实现详解见 [`observability.md`](observability.md)

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

## 怎么跑（当前验收）

```bash
cd projects/p2-ai-gateway && python3 app.py
# DONE · P2 Router + Semantic Cache + Prompt Version green  EXIT:0
```

- 14 段断言全绿：Router 5 段 + Cache 4 段 + Prompt Version 5 段（版本钉扎/alias 发布回滚/A/B 稳定分桶/版本不可变/全链路：应用层 SDK 治理 + Gateway 侧 version_tag 归因）
- Router 复用 P1 `LLMProvider` 契约（`chat(messages)→{content,usage,provider}`），自身即 Provider，可组合热插
- `ScriptedProvider` 离线可跑；生产替换为 P1 `HttpGatewayProvider`（同契约），Router 无感

## 建议里程碑

1. **M1 Provider 抽象 + Fallback/Retry**：统一接口 + 可靠性（Provider 抽象+元数据已落 `providers.py`；Fallback/Retry 待）
2. **M2 Model Router** ✅：按成本/延迟/能力/balanced 四策略选模型，能力硬过滤 + 无候选 RouteError
3. **M3 Semantic Cache** ✅：embedding+余弦阈值命中 + TTL/容量 + 阈值防误命中（stdlib embedding；生产换真语义 embedding + Redis/FAISS，方法不变）
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
