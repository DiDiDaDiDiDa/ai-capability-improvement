# Circuit Breaker 设计说明：熔断保护

> 所属项目：P2 · AI Gateway ｜ 对应模块 06 ｜ 状态：设计说明（未落代码）

## 一句话总结

熔断器给每个 Provider 装一个「保险丝」：失败率超阈值就**跳闸（Open）**，一段时间内直接拒绝对它的调用（快速失败 + 走 Fallback），不再让请求白白超时。冷却后**半开（Half-Open）**
放几个探针试水，成功则**恢复（Closed）**，失败则继续跳闸。

## 0. 为什么需要它（和 Retry 的分工）

Retry/Fallback 是「出错了怎么补救」，熔断是「**别再撞已知的墙**」。一个 Provider 已经
持续挂了，还对它 Retry 3 次 × 每次超时 30s = 每个请求白等 90s 才 Fallback。熔断跳闸后
**立即**失败转 Fallback，把「慢失败」变「快失败」，保护整体延迟和资源。

## 1. 三态机

```
        失败率 ≥ 阈值
 Closed ───────────────► Open
   ▲                       │ 冷却时间到
   │ 探针成功              ▼
   └──────── Half-Open ◄───┘
              │ 探针失败
              └────► Open（重新计时）
```

| 状态 | 行为 |
|------|------|
| **Closed** | 正常放行，统计滑动窗口内失败率 |
| **Open** | 直接拒绝（快速失败），不调 Provider；到冷却时间转 Half-Open |
| **Half-Open** | 只放行少量探针；成功→Closed，失败→Open 重新计时 |

## 2. 组件设计

```
CircuitBreaker（每 Provider 一个实例）
  state, failure_window（滑动计数）, opened_at
  allow() -> bool           # Open 且未到冷却 → False（快速失败）
  record(success: bool)     # 更新窗口；Closed 下失败率超阈→Open；Half-Open 下据结果转移

BreakeredRouter / 集成点：
  Router 选 Provider 前先问 breaker.allow()：
    False → 视该 Provider 不可用，跳过（等价 Fallback 到下一个）
    True  → 调用后 breaker.record(成功与否)
```

- **触发条件**：滑动窗口失败率（如最近 20 次 ≥ 50% 失败）或连续失败数，二选一或组合。
- **冷却时间**：Open 持续多久转 Half-Open（如 30s），太短反复跳、太长恢复慢。
- **与 Router 联动**：熔断把「跳闸的 Provider」移出健康池，Router 只在健康池里选——
  熔断 + Fallback + Router 三者天然咬合。

## 3. 成品长什么样（示意，非运行输出）

```
premium-strong 连续 503：
  失败 1..10（窗口失败率 0.5）→ 阈值命中 → state=Open
  后续请求 → breaker.allow()=False → 快速失败(不等超时) → Router 跳过它选 balanced-mid
  30s 后 → state=Half-Open → 放 1 个探针
     探针成功 → state=Closed（恢复）
     探针失败 → state=Open（再等 30s）
usage.circuit = {"premium-strong": "open", "balanced-mid": "closed"}
```

## 4. 踩过的坑 / 注意点

- **没有熔断只有 Retry**：对死掉的 Provider 反复重试超时，每个请求都慢失败，拖垮整体延迟。
- **冷却时间拍脑袋**：太短→刚恢复就被打回；太长→Provider 好了还在被拒。需按恢复特征调。
- **Half-Open 放太多探针**：Provider 还没缓过来就被探针洪水二次打死。半开只放少量。
- **全局一个熔断器**：必须**每 Provider 一个**，否则一个挂了误伤全部。
- **熔断状态不可观测**：跳闸了没人知道 = 静默降级。状态要回填 + 告警。

## 5. 面试问答（自测）

- **Q: 熔断解决什么 Retry 解决不了的问题？** 避免对已知挂掉的 Provider 反复慢失败；把慢失败变快失败。
- **Q: 三个状态？** Closed 正常统计；Open 快速拒绝；Half-Open 放探针试恢复。
- **Q: 什么时候跳闸？** 滑动窗口失败率或连续失败数超阈值。
- **Q: Half-Open 为什么只放少量探针？** 防止 Provider 未恢复就被探针二次打死。
- **Q: 和 Router/Fallback 怎么咬合？** 跳闸的 Provider 移出健康池，Router 只在健康池选，等价自动 Fallback。

## 参考

- 组合位置：每 Provider 一个 breaker，Router 选型前查 `allow()`、调用后 `record()`
- 配套：`fallback-retry.md`（熔断决定「还要不要试这个 Provider」）
- 经典模式：Netflix Hystrix / resilience4j 的 CircuitBreaker
