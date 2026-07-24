# Model Router 实现说明：怎么实现 / 为什么这样 / 指标从哪来

> 所属项目：P2 · AI Gateway ｜ 对应模块 06 ｜ 日期：2026-07-23
> 代码：`p2gateway/router.py` + `p2gateway/providers.py`，验收 `app.py`（5 段全绿 EXIT:0）

## 一句话总结

Model Router 把「选哪个模型」拆成**硬过滤（必须满足的门槛）+ 软排序（候选里挑最优）**
两层；策略（cost/latency/quality/balanced）只作用于软排序层；Router 自身实现 P1 的
`LLMProvider.chat` 契约，所以对调用方它就是「一个更聪明的 Provider」。

## 1. 整体架构：Router 在哪一层

```
调用方(P1 / 业务)
      │  chat(messages, strategy=…, need_caps=…, max_cost=…)
      ▼
┌─────────────── ModelRouter（本身是 LLMProvider）───────────────┐
│  route(req):                                                   │
│    ① 硬过滤 _filter  → 淘汰不满足能力/上下文/预算/延迟的候选      │
│    ② 软排序 _score   → 在幸存者里按 strategy 打分，取最高        │
│  chat(messages):                                               │
│    route() 选中 → 委托 provider.chat() → 回填 usage.routing     │
└────────────────────────────────────────────────────────────────┘
      │ 委托执行
      ▼
ScriptedProvider(cheap-fast) / (balanced-mid) / (premium-strong)
  每个挂一份 ModelProfile：cost_per_1k / latency_ms / quality / capabilities
```

关键点：**Router 与被路由的 Provider 是同一个 `chat` 契约**，所以

- 调用方无感：P1 把出口从单个 Provider 换成 Router，代码不动；
- 可组合：Router 里还能塞另一个 Router（分层路由：先按地域再按成本）。

## 2. 怎么实现：两层决策

### 2.1 硬过滤（`_filter`）——门槛，不满足直接淘汰

按序检查每个 Provider，命中任一淘汰条件就记原因、踢出候选池：

| 淘汰条件 | 判据 | 记录的原因 |
|---------|------|-----------|
| 不健康 | `not p.healthy` | `unhealthy` |
| 能力缺失 | `not profile.supports(need_caps)` | `missing_caps:[…]` |
| 上下文超限 | `est_context > profile.max_context` | `context_over:…` |
| 太贵 | `cost_per_1k > max_cost_per_1k` | `too_expensive:…` |
| 太慢 | `latency_ms > max_latency_ms` | `too_slow:…` |

`ModelProfile.supports` 就是集合包含判断：`needed.issubset(self.capabilities)`。
过滤后返回 `(幸存池, {淘汰名: 原因})`——**淘汰原因全程留痕**，是可审计的基础。

### 2.2 软排序（`_score`）——候选里按策略打分

打分约定「**分越高越好**」，四策略：

```
cost      → -cost_per_1k          # 越便宜分越高（取负）
latency   → -latency_ms           # 越快分越高（取负）
quality   →  quality              # 越强分越高（0~1 直接用）
balanced  →  0.4*C + 0.3*L + 0.3*Q  # 三维归一化加权
```

`balanced` 的 C/L/Q 由 `_norm()` 做 **min-max 归一化**到 [0,1]，其中成本、延迟
「越小越好」要翻转（`invert=True`）：

```
归一化：x = (value - min) / (max - min)
成本/延迟：得分 = 1 - x   （小的拿高分）
质量：    得分 = x       （大的拿高分）
池内全相等：记满分 1.0（避免除零）
```

权重 `0.4/0.3/0.3` 表达「成本略重于延迟与质量」，是可调旋钮，不是真理。

### 2.3 决策落地（`route` / `chat`）

- `route(req)` **只选不执行**：排序后取第一，打包成 `RouteDecision`
  （chosen / strategy / score / candidates / rejected）返回——纯函数，好测。
- `chat(messages)` 才执行：`route()` 选中 → `provider.chat()` 委托 →
  把决策回填进 `usage.routing`，并标 `resp["router"]="model-router"`。
- 排序键用 `(-score, name)`：分数相同时按名字排，**保证选择稳定可复现**（否则
  相同输入可能选到不同 Provider，验收就飘了）。

## 3. 为什么这样实现（设计决策）

### 3.1 为什么硬过滤和软排序分离

如果混在一起打分（比如「能力不满足就减很多分」），会出现**灾难性误选**：一个不支持
`vision` 的便宜模型，靠成本优势把分数拉回来被选中 → 请求直接失败。能力/上下文是
**正确性门槛**，不是偏好；成本/延迟是**偏好**。门槛用硬过滤（要么进要么出），偏好用
软排序（比大小）。验收第 2 段就是证据：`need vision + strategy=cost`，最贵的
premium 反而被选中——因为便宜的都不支持 vision，成本偏好在门槛面前不作数。

### 3.2 为什么无候选要报错，不静默降级

`route()` 发现幸存池为空时抛 `RouteError`，而不是「随便选一个」或「放宽约束选个最接近的」。
理由：**选错模型比不选更危险**。调用方要 `audio` 能力，没有 Provider 支持，静默降级到
一个不支持的模型 = 线上返回垃圾结果还查不出为什么。显式报错把决策权交回上层——
上层可以选择放宽约束重试、走人工、或返回「暂不支持」。这是 owner 意识：宁可显式失败。

### 3.3 为什么 Router 复用 P1 的 `LLMProvider` 契约、自己也是 Provider

P1 已定义 `chat(messages)→{content,usage,provider}`（`p1rag/gateway.py`）。Router 若
另造一套接口，P1 接入就要改代码、加适配层。让 Router **实现同一个契约**：

- P1 出口 `P1_PROVIDER=http` 指到 Router，零改动；
- Router 可被另一个 Router 包裹（分层路由）；
- 单个 Provider 和一组 Provider 对调用方**长得一模一样**（组合模式）。

这就是「不重造轮子」落到接口层的具体含义。

### 3.4 为什么决策要回填到 `usage.routing`

选型如果是黑箱，线上就会有「为什么这条请求走了贵模型」的无头案。把
chosen/candidates/rejected 回填进 usage，等于给每次路由**盖了审计章**：事后能复盘
「哪些候选被什么原因淘汰、最终为什么选它」。可观测性是 Gateway 的一等公民，不是事后补。

## 4. 成本 / 延迟 / 能力指标从哪来（重点）

**先说实话：当前代码里这三个指标是 `ModelProfile` 上的教学脚本值（硬编码），
不是运行时采集的。** `app.py` 的 `build_fleet()` 手写了三档模型的画像：

```python
ModelProfile(name="cheap-fast", cost_per_1k=0.10, latency_ms=200, quality=0.60,
             capabilities=frozenset({"zh","chat"}), max_context=8192)
```

这是刻意的：本次里程碑要验证的是**路由决策逻辑**（两层过滤+四策略），不是指标采集
管线。指标写死可复现，验收才能断言「cost 策略必选 cheap-fast」。下面讲每个指标
**生产里真正怎么来**——这也是面试会追问的点。

### 4.1 成本（cost_per_1k）——静态配置为主

- **来源**：各 Provider 官方定价页（OpenAI/Anthropic/Gemini/Qwen/DeepSeek），
  input/output 分别计价，Router 里存一份**定价表配置**（YAML/JSON），随版本更新。
- **为什么静态**：定价变化频率低（周/月级），不需要实时采集；用配置 + 定期同步即可。
- **精细化**：真实成本 = `in_tokens*price_in + out_tokens*price_out`，本 demo 用
  合并均价 `cost_per_1k` 简化。生产建议 in/out 拆开，路由前用 prompt 长度**预估**
  成本，路由后用实际 usage **核销**（对应 Cost Dashboard 能力项）。

### 4.2 延迟（latency_ms）——线上监控滑动窗口

- **来源**：**不能静态写死**，延迟随负载/时段/网络波动。生产从**可观测性系统**
  （Prometheus/OpenTelemetry）取每个 Provider 的**滚动分位数**（p50/p95/p99），
  用 p95 而非均值（尾延迟才是体感杀手）。
- **采集方式**：Gateway 每次真实调用记录 `latency_ms` → 时序库 → Router 定期拉取
  最近 N 分钟的滑窗分位数刷新 profile。
- **闭环**：这与熔断/健康检查共享同一份实时信号——延迟飙高既影响路由排序，也触发
  Circuit Breaker（后续里程碑）。本 demo 的 `healthy` 字段就是这个信号的占位。

### 4.3 能力（capabilities）——模型能力矩阵/注册表

- **来源**：一份**模型能力矩阵**（哪个模型支持 vision/function-calling/json-mode/
  长上下文/中文/代码…），来自各家模型文档 + 内部实测，维护成配置或注册中心。
- **为什么要实测补充**：官方宣称支持 ≠ 生产可用（如某模型 function-calling 稳定性差），
  内部要跑能力回归测试给每个能力打「可用/不可用」标，比官方文档更可信。
- **上下文窗口**（`max_context`）：属于能力的一部分，来自模型规格，用于硬过滤超长请求。

### 4.4 小结：指标的「三种时效」

| 指标 | 变化频率 | 生产来源 | 本 demo |
|------|---------|---------|---------|
| 成本 | 低（月级）| 定价页 → 静态配置 | 硬编码 |
| 延迟 | 高（分钟级）| 监控滑窗 p95 → 动态刷新 | 硬编码 |
| 能力 | 低（版本级）| 能力矩阵 + 内部实测 | 硬编码 |

**一句话**：成本和能力可以「配置 + 定期同步」，延迟必须「实时监控 + 动态刷新」——
把三者都当静态值是初级 Router，把延迟做成动态信号才是生产级。

## 5. 踩过的坑 / 易混淆点

- **能力当偏好打分**：把「不支持 vision」做成扣分而非淘汰 → 便宜模型靠成本翻盘被选，
  请求失败。能力是门槛，必须硬过滤。
- **无候选静默降级**：兜底选个「最接近的」看似友好，实则埋线上事故。显式 `RouteError`。
- **排序不稳定**：只按 score 排，分数相同时选择随机漂移 → 验收/复现失败。加 name 兜底。
- **延迟写死**：把 latency 当静态配置是最常见的错——它是唯一必须实时的指标。
- **均价掩盖真成本**：合并 `cost_per_1k` 简化教学；生产 output 通常比 input 贵数倍，
  必须 in/out 拆开算，否则长输出任务成本估偏。

## 6. 面试问答（自测）

- **Q: Model Router 怎么兼顾成本和质量？**
  A: 硬过滤先保证正确性（能力/上下文/预算门槛），软排序再按策略选偏好；balanced
  策略把成本/延迟/质量 min-max 归一化后加权，权重是可调旋钮。

- **Q: 成本/延迟/能力这些指标从哪来？**
  A: 成本来自定价页做静态配置（月级更新）；能力来自模型能力矩阵 + 内部实测（版本级）；
  延迟必须从监控系统取实时 p95 滑窗动态刷新（分钟级）——三者时效不同，延迟是唯一必须实时的。

- **Q: 没有模型满足要求时怎么办？**
  A: 抛错不降级。选错模型比不选更危险，把决策权交回上层（放宽约束/人工/拒绝）。

- **Q: 为什么 Router 也实现 chat 契约？**
  A: 组合模式——单 Provider 和一组 Provider 对调用方长得一样，P1 出口零改动接入，
  且 Router 可嵌套做分层路由。

## 参考资料

- 代码：`p2gateway/router.py`（决策）、`p2gateway/providers.py`（画像）、`app.py`（验收）
- 契约来源：`projects/p1-enterprise-rag/p1rag/gateway.py` 的 `LLMProvider`
- 模块 06 笔记：`docs/06-ai-infra/serving-batching-paged.md`（Serving 侧的延迟/吞吐）
