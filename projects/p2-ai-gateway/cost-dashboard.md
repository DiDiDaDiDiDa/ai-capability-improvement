# Token Cost Dashboard 设计说明：成本可视化怎么做

> 所属项目：P2 · AI Gateway ｜ 对应模块 06 ｜ 状态：**已落代码**
> （实现 `p2gateway/cost_dashboard.py`，验收 `app.py` 第 15/16 段）

## 一句话总结

Cost Dashboard 不产生新数据，它是一层「**观测 → 聚合 → 渲染**」：把每次调用 usage 里
已有的 `cost_usd / tokens / latency / version_tag / cache.status / routing.chosen`
收集起来，按维度聚合，算出「实付、名义、缓存省下」三笔账并渲染成面板。

## 1. 数据从哪来（不新造）

前面几个能力已经在 `usage` 里留好了所有信号，Dashboard 只是消费方：

| 字段 | 谁写的 | 用途 |
|------|--------|------|
| `cost_usd` | Provider（成本画像 × tokens） | 成本聚合 |
| `prompt/completion_tokens` | Provider | token 消耗 |
| `latency_ms` | Provider | 延迟统计 |
| `routing.chosen` | Router | 按模型归因成本 |
| `cache.status` | Cache | 算命中省下的钱 |
| `version_tag` | 应用层 SDK | 按 prompt 版本归因成本 |

## 2. 三个组件

```
gateway 链路（Cache→Router→Provider）
      │  每次 chat 返回 resp.usage
      ▼
MeteredProvider（装饰器，套最外层）── 抽一条 UsageRecord 记进 tracker
      ▼
CostTracker ── 累积 records + 按 provider/version/cache 多维聚合
      ▼
render_dashboard ── 文本面板：总账 + 分维度表 + 缓存节省
```

- **`MeteredProvider`**：实现 `chat` 契约的装饰器，套在**最外层**（Metered→Cache→Router）。
  为什么最外层：成本/缓存命中/选型都要等下游执行完才在 usage 里齐全，套里面会漏。
- **`CostTracker`**：持有 `list[UsageRecord]`，提供 `by_provider()` / `by_version()` /
  `by_cache()` 聚合，以及 `totals()`（总请求数、总 token、实付、名义、省下）。
- **`render_dashboard`**：把聚合结果画成 Unicode 表格，纯 stdlib。

## 3. 关键指标：缓存省了多少钱

这是 Dashboard 最有价值的一笔账（回答「上缓存到底值不值」）：

```
命中(hit)   → 实付 actual = 0，名义 listed = 这条本来要花的成本 → saved += listed
未命中(miss)→ 实付 actual = listed
节省率 = Σsaved / Σlisted
```

`UsageRecord` 拆成 `listed_cost` 和 `actual_cost` 两个字段就是为了算这笔账。

## 4. 成品长什么样（示意）

```
┌──────────────── Token Cost Dashboard ────────────────┐
 总请求 42 | 总 token 18,540 | 实付 $0.83 | 名义 $1.21
 缓存节省 $0.38 (31.4%) | 命中率 28.6%

 by model            reqs   tokens   actual$   avg_ms
 ─────────────────────────────────────────────────────
 cheap-fast            25    6,200    $0.06      200
 balanced-mid          12    8,100    $0.32      500
 premium-strong         5    4,240    $0.45     1200

 by prompt version   reqs   actual$   share
 ─────────────────────────────────────────────
 qa@v1                 30    $0.51     61%
 qa@v2                 12    $0.32     39%
─────────────────────────────────────────────────────────
```

## 5. 指标从哪来（诚实说明）

和 Model Router 同一套：教学实现里 `cost_usd/latency_ms/tokens` 由脚本 Provider 按
画像生成；**生产替换为真实值**——成本 = 真实 in/out tokens × 定价、延迟 = 真实端到端耗时、
token = 真实 tokenizer 计数。采集/聚合/渲染逻辑不变，只换数据源。真实 Dashboard 通常还会
把 records 落时序库（Prometheus/ClickHouse）+ Grafana 出图，本设计是其最小内核。

## 6. 踩过的坑 / 注意点

- **采集器套错层**：套 Router 里面 → 拿不到 cache.status，缓存节省算不出。必须最外层。
- **命中还按名义计费**：命中实付是 0，混淆会把成本算高。listed / actual 必须分开。
- **token 粗估当精确**：教学用 `len//4`，生产必须真 tokenizer，否则成本偏差大。
- **只看总额不看维度**：按 model/version 拆开才能定位「哪个模型/哪版 prompt 在烧钱」。

## 7. 面试问答（自测）

- **Q: 成本可视化的数据从哪来？** 复用各层已写进 usage 的 cost/tokens/latency + routing/cache/version_tag，Dashboard 只做聚合，不新造。
- **Q: 缓存省的钱怎么算？** 命中时实付记 0、名义记为本来要花的，saved 累加名义；节省率 = Σsaved/Σlisted。
- **Q: 采集器为什么套最外层？** 成本/命中/选型要下游执行完才在 usage 齐全，套里面会漏字段。
- **Q: 教学值和生产值差别？** 教学用脚本画像 + len//4 估 token；生产用真定价 × 真 tokenizer + 时序库落盘。

## 参考

- 复用信号：`router.py`(routing) / `semantic_cache.py`(cache) / `prompt_client.py`(version_tag) / `providers.py`(cost_usd)
- 对照：`model-router.md` 第 4 节（指标来源同一套逻辑）
