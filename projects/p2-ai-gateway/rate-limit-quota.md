# Rate Limit / Quota 设计说明：限流与配额

> 所属项目：P2 · AI Gateway ｜ 对应模块 06 ｜ 状态：**已落代码**
> （实现 `p2gateway/rate_limit.py`，验收 `app.py` 第 20 段）

## 一句话总结

Rate Limit 管**瞬时速率**（每秒/每分多少请求或 token，防突发打爆下游）；Quota 管
**累计用量**（每天/每月总配额，防超预算）。两者套在链路**靠前**（Guardrail 之后、
Cache 之前），超限的请求在花钱之前就被挡下。

## 0. Rate Limit 与 Quota 的分工

|      | Rate Limit（限流）      | Quota（配额）            |
| ---- | ------------------- | -------------------- |
| 管的维度 | 速率（req/s、token/min） | 累计量（req/day、$/month） |
| 时间尺度 | 秒级滑动                | 天/月周期                |
| 超限处置 | 拒绝(429) / 排队 / 降级   | 拒绝 / 告警 / 切降级模型      |
| 目的   | 防突发打爆、公平调度          | 防超预算、成本封顶            |

## 1. 限流算法：Token Bucket（推荐）

```
Token Bucket：桶容量 capacity，按 refill_rate 匀速补令牌。
  每来一个请求取 1 个（或按 token 数取 N 个）令牌：
    有令牌 → 放行，扣减
    无令牌 → 拒绝 / 排队
特点：允许一定突发（桶里存量），长期速率受 refill_rate 约束。
```

对比：漏桶（严格匀速，不允许突发）、固定窗口（有临界突刺问题）、滑动窗口（更平滑但重）。
**LLM 网关常用 token bucket**——既限速又容忍合理突发。按 **token 数**而非请求数计量更贴成本。

## 2. 组件设计

```
RateLimitedProvider（装饰器，套靠前，Cache 之前）
  按 key（api_key / user_id / tenant）取各自的桶与配额计数
  chat(messages):
    key = 从 kwargs 取调用方标识
    if not bucket[key].take(cost_tokens): return 429_response   # 限流
    if quota[key].used + cost >= quota[key].limit: return quota_exceeded  # 配额
    resp = inner.chat(...)
    quota[key].used += resp.usage.total_tokens                  # 事后核销
    return resp
```

- **多租户隔离**：按 key 分桶分配额，一个租户超限不影响其他人。
- **预估 vs 核销**：请求前用 prompt 长度**预估** token 占额度，返回后用真实 usage **核销**差额。
- **归因**：回填 `usage.limit = {remaining_rate, remaining_quota, key}`，调用方可感知余量。

## 3. 分布式的现实（诚实说明）

上面是**单机内存**版，教学足够。真实多实例 Gateway 必须**共享状态**，否则每个实例各限各的
= 总量翻 N 倍失效。生产做法：

- **Redis** 存桶/计数，用原子操作（`INCR`+`EXPIRE` 或 Lua 脚本）保证并发正确。
- 或用专门的限流中间件（Envoy ratelimit、Kong 插件等）。

本设计是单机内核，**分布式一致性是它到生产的主要 gap**，不能假装单机版能直接上多实例。

## 4. 成品长什么样（示意，非运行输出）

```
key=tenant-A, 桶容量 10, refill 5/s：
  瞬时来 15 个请求 → 前 10 个放行（吃桶存量）→ 后 5 个 429（桶空）
  1s 后补 5 令牌 → 再放行 5 个
key=tenant-A, 月配额 100万 token, 已用 99.8万：
  新请求预估 5000 token → 99.8万+5000 < 100万 放行
  再来一个 → 超额 → quota_exceeded（或切降级模型继续服务）
usage.limit = {remaining_rate: 3, remaining_quota: 2000, key: "tenant-A"}
```

## 5. 踩过的坑 / 注意点

- **限流放在花钱之后**：超限请求已经调了模型，钱花了才拒绝。必须靠前（Cache 之前）。
- **单机限流上多实例**：每实例各限各的，总量失效。生产必须 Redis 共享状态。
- **按请求数不按 token**：一个长请求和一个短请求算一样，与真实成本脱节。按 token 计量更准。
- **只拒绝不给余量**：调用方不知道还剩多少，无法自我调度。回填 remaining。
- **配额只预估不核销**：预估偏差累积会让配额算不准。事后用真实 usage 核销。

## 6. 面试问答（自测）

- **Q: Rate Limit 和 Quota 区别？** 前者管瞬时速率（防打爆），后者管累计用量（防超预算）。
- **Q: 为什么用 token bucket？** 既限长期速率又容忍合理突发；按 token 计量贴成本。
- **Q: 放链路哪一层？** 靠前——Guardrail 之后、Cache 之前，超限在花钱前挡下。
- **Q: 单机限流上多实例会怎样？** 每实例各限各的，总量翻倍失效；需 Redis 共享状态 + 原子操作。
- **Q: 预估和核销？** 请求前按 prompt 长度预估占额，返回后用真实 usage 核销差额。

## 参考

- 组合位置：`RateLimitedProvider(CachedProvider(...))`，靠近链路入口
- 算法：Token Bucket / Leaky Bucket / 滑动窗口；生产用 Redis 原子计数
