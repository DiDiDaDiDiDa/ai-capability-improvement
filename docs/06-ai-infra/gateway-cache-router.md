# Gateway / Cache / Router 总览：九大能力如何串成生产链路

> 所属模块：06 · AI Infra ｜ 学习日期：2026-08-10
> 项目：`projects/p2-ai-gateway/`（`app.py` 九大能力 22 段全绿 EXIT:0）
> 实现细账：各能力独立笔记在项目目录（见文末索引），本文只讲**分层与咬合**

## 一句话总结

AI Gateway 不是「多一个 HTTP 转发」，而是把 **选型（Router）/ 省钱（Cache）/ 兜底（Resilience+CB）/ 治理（Limit+Guardrail）/ 归因（Cost+Obs）** 叠成同一条 `chat` 契约；每一层都是 Provider 装饰器，**顺序决定正确性与成本**。

## 我的理解

```
Client
  │  chat(messages, …)
  ▼
┌──────────── Gateway 装饰器栈（由外到内）────────────┐
│  Observability   ── 开 span、记延迟/错误，不改语义     │
│  Guardrail       ── 输入 block / 输入输出 PII mask     │
│  RateLimit/Quota ── 限流 + 配额（花钱前挡）           │
│  Cost Dashboard  ── 最外可观测侧采集 usage 聚合       │
│  Semantic Cache  ── 语义命中直接返回，省 LLM 调用     │
│  Resilience      ── Retry 瞬时 + Fallback 换候选     │
│  Circuit Breaker ── 按 Provider 三态跳闸，快失败     │
│  Model Router    ── 硬过滤 + 软排序选模型             │
└──────────────────────┬─────────────────────────────┘
                       ▼
              Multi Provider（同 chat 契约）
                       ▼
              Serving（模块内另一篇：KV/Batching/Page/Spec）
```

**底层逻辑**：每一层只做一件事、回填自己的 `usage.*` 字段，下游/上游互不感知内部——这叫**同一契约上的分层解耦**。第 22 段验收就是证明：8 层装饰器叠完，一次请求字段全链路咬合。

### 1. Router：硬过滤 + 软排序

- **硬过滤**：能力 / 上下文窗口 / 预算 / 延迟上限 —— 不满足直接淘汰
- **软排序**：cost / latency / quality / balanced 只在幸存者里打分
- Router **自己就是** `LLMProvider`，对调用方是「更聪明的一个 Provider」
- 细账：[`model-router.md`](../../projects/p2-ai-gateway/model-router.md)

### 2. Semantic Cache：跨请求省调用

- query → embedding → 与缓存向量余弦 ≥ 阈值 → 命中整段响应
- 阈值是灵魂：高了命中率低，低了**误命中**返回错答案
- TTL / 容量淘汰；可套在 Router **外层**（命中时连路由都省）
- **≠ KV Cache**（推理层、单次生成内、K/V 张量）
- 细账：[`semantic-cache.md`](../../projects/p2-ai-gateway/semantic-cache.md)

### 3. Prompt Version：应用层治理，Gateway 只归因

- 渲染 `id+变量 → messages` 在**应用层 SDK**（复用模块 02 Registry）
- Gateway 只收不透明 `version_tag`，用于成本/缓存/路由归因
- 反模式：把模板渲染焊进 Gateway（基础设施耦合业务语义）
- 细账：[`prompt-version.md`](../../projects/p2-ai-gateway/prompt-version.md)

### 4. Cost Dashboard：观测 → 聚合 → 渲染

- 不产生新数据，消费 `usage` 里已有 cost/tokens/latency/cache/routing/version
- 三笔账：实付 / 名义 / **缓存省下**（ROI）
- 细账：[`cost-dashboard.md`](../../projects/p2-ai-gateway/cost-dashboard.md)

### 5. Fallback + Retry：补救，不是预防

| | Retry | Fallback |
|---|---|---|
| 解决 | 同一 Provider **瞬时**抖动 | Provider **持续**不可用 |
| 动作 | 退避重试 N 次 | 切下一候选 |
| 触发 | 超时 / 429 / 5xx | 重试耗尽 / 明确不可用 |

- 4xx（参数/违规）**不要重试**；错误要分类
- 细账：[`fallback-retry.md`](../../projects/p2-ai-gateway/fallback-retry.md)

### 6. Circuit Breaker：别再撞已知的墙

- 三态：Closed → Open（失败率跳闸）→ Half-Open（探针）→ 恢复或再跳
- 和 Retry 分工：Retry/Fallback 是「出错怎么补」；熔断是「已知挂了就快失败」
- 每 Provider 一个 breaker，与 Fallback/Router 咬合
- 细账：[`circuit-breaker.md`](../../projects/p2-ai-gateway/circuit-breaker.md)

### 7. Guardrail：最外层安全阀

- 输入：注入 / 违规 → **block**（不进 Cache、不调模型）
- 输入/输出：PII → **mask**（密钥全遮、联系方式留局部）
- 必须在昂贵路径之前，省钱又安全
- 细账：[`guardrail.md`](../../projects/p2-ai-gateway/guardrail.md)

### 8. Rate Limit / Quota：速率 vs 累计

| | Rate Limit | Quota |
|---|---|---|
| 维度 | 瞬时速率（req/s、token/min） | 累计量（$/day） |
| 算法 | Token Bucket 常用 | 周期核销 |
| 目的 | 防突发打爆、公平 | 防超预算 |

- 多租户按 key 隔离；靠前放置，花钱前挡
- 细账：[`rate-limit-quota.md`](../../projects/p2-ai-gateway/rate-limit-quota.md)

### 9. Observability：Trace / Metrics / Log

- Tracing：单请求 span 树 + 共享 `trace_id`
- Metrics：QPS、p50/p95/p99、错误计数（**看 p95 别只看均值**）
- Logging：按 request_id 下钻细节
- 细账：[`observability.md`](../../projects/p2-ai-gateway/observability.md)

## 核心要点

- **同一 `chat` 契约**：所有层可热插，P1/P3 只认 Provider 接口
- **装饰器顺序是产品决策**：Guardrail/Limit 靠前，Cache 在 Router 外可省路由，Cost/Obs 吃全链路 usage
- **usage 回填是咬合点**：`routing` / `cache` / `guardrail` / `limit` / `trace` / `resilience` 各写各的字段
- **Serving 与 Gateway 分层**：吞吐/显存优化在 Serving（见 [`serving-batching-paged.md`](serving-batching-paged.md)）；治理/选型/省钱在 Gateway

## 动手记录

```bash
python3 projects/p2-ai-gateway/app.py
# 22 段：Router / Cache / Prompt / Cost / Resilience / CB /
#        Guardrail / RateLimit / Observability / 全栈 8 层咬合
# DONE · P2 AI Gateway 九大能力全绿  EXIT:0
```

观察要点（实跑时对照）：

- Cache 阈值：相似句 hit、无关句 miss（防误命中）
- 突发限流：桶打空后拒绝，补令牌恢复；多租户互不影响
- 熔断：失败率跳闸后请求立刻走 Fallback，不再傻等超时
- 全栈段：一次请求 `provider` / `guardrail` / `limit` / `trace_id` / `cache` / `routing` 字段齐

## 踩过的坑 / 易混淆点

- **KV Cache ≠ Semantic Cache**：推理算子级 vs Gateway 应用级；单次生成内 vs 跨请求
- **Retry 一切错误**：4xx 重试只会放大延迟；要错误分类
- **熔断 = Fallback**：熔断是快失败保险丝，Fallback 是换候选；常组合但不是一回事
- **Prompt 渲染塞进 Gateway**：业务变量污染基础设施；正确是应用层 SDK + `version_tag`
- **Cost 自己造数**：应消费 usage，别在 Dashboard 重算 tokens
- **只看平均延迟**：长尾被均值掩盖，体感看 p95/p99
- **Cache 套太内层**：命中仍可能白跑 Guardrail 之外的贵路径；常见是 Cache 在 Router 外

## 面试问答（自测）

- **Q: Gateway 的 Fallback 和 Circuit Breaker 分别处理什么？**  
  Fallback：某 Provider 不可用时换候选，保证请求仍完成。  
  Circuit Breaker：失败率超阈值后对该 Provider 跳闸，快失败、避免 Retry 空耗；冷却后半开探针。

- **Q: Semantic Cache 怎么判断命中？可能出什么错？**  
  query embedding 与缓存向量余弦 ≥ 阈值即命中。错：阈值过低误命中（答非所问）、未按租户/模型隔离串数据、无 TTL 返回过期答案。

- **Q: 多 Provider 统一接口难点？**  
  能力差（工具/视觉/JSON mode）、参数差（max_tokens 语义）、错误码差、计费差；要用统一 `chat` 契约 + 元数据画像（cost/latency/caps）让 Router 可决策。

- **Q: Model Routing 怎么兼顾成本与质量？**  
  硬过滤保证能力底线；软排序用 balanced/ cost 策略打头便宜模型，质量敏感或失败时 Fallback 到贵模型；用 Cost Dashboard 验证 ROI。

- **Q: KV Cache 和 Semantic Cache 一回事吗？**  
  不是。见上文易混淆点；Serving 篇也有对照。

- **Q: 装饰器顺序为什么重要？**  
  Guardrail/Limit 靠前避免脏请求与超预算请求烧钱；Cache 位置决定命中时省到哪一层；Obs/Cost 靠外才能采到全链路字段。

## 能力笔记索引（项目侧）

| 能力 | 代码 | 笔记 |
|------|------|------|
| Model Router | `p2gateway/router.py` | [`model-router.md`](../../projects/p2-ai-gateway/model-router.md) |
| Semantic Cache | `p2gateway/semantic_cache.py` | [`semantic-cache.md`](../../projects/p2-ai-gateway/semantic-cache.md) |
| Prompt Version | `p2gateway/prompt_client.py` | [`prompt-version.md`](../../projects/p2-ai-gateway/prompt-version.md) |
| Cost Dashboard | `p2gateway/cost_dashboard.py` | [`cost-dashboard.md`](../../projects/p2-ai-gateway/cost-dashboard.md) |
| Fallback+Retry | `p2gateway/resilience.py` | [`fallback-retry.md`](../../projects/p2-ai-gateway/fallback-retry.md) |
| Circuit Breaker | `p2gateway/circuit_breaker.py` | [`circuit-breaker.md`](../../projects/p2-ai-gateway/circuit-breaker.md) |
| Guardrail | `p2gateway/guardrail.py` | [`guardrail.md`](../../projects/p2-ai-gateway/guardrail.md) |
| RateLimit/Quota | `p2gateway/rate_limit.py` | [`rate-limit-quota.md`](../../projects/p2-ai-gateway/rate-limit-quota.md) |
| Observability | `p2gateway/observability.py` | [`observability.md`](../../projects/p2-ai-gateway/observability.md) |
| 总验收 | `app.py` | [`README.md`](../../projects/p2-ai-gateway/README.md) |

## 参考资料

- 项目实现与验收：`projects/p2-ai-gateway/`
- Serving 四机制（下游）：[`serving-batching-paged.md`](serving-batching-paged.md)
- Prompt Registry（上游复用）：模块 02 `experiments/prompt-sdk/`
- Provider 契约来源：`projects/p1-enterprise-rag/` 的 `LLMProvider`
