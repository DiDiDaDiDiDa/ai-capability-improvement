# Fallback + Retry 设计说明：Provider 故障兜底

> 所属项目：P2 · AI Gateway ｜ 对应模块 06 ｜ 状态：设计说明（未落代码）

## 一句话总结

Retry 处理**同一 Provider 的瞬时抖动**（超时/限流/5xx，退避重试）；Fallback 处理
**某 Provider 整体不可用**（换下一个候选）。两者组合套在 Router 附近，保证「一个模型
挂了，请求仍能被另一个模型完成」。

## 0. Retry 与 Fallback 的分工（别混）

|     | Retry                 | Fallback             |
| --- | --------------------- | -------------------- |
| 解决  | 同一 Provider 的**瞬时**故障 | 某 Provider **持续**不可用 |
| 动作  | 对同一个重试 N 次（带退避）       | 切到下一个候选 Provider     |
| 触发  | 超时、429、503 等**可重试**错误 | 重试耗尽 / 明确不可用         |
| 风险  | 重试放大延迟和成本             | 兜底模型质量/成本可能更差        |

**关键**：不是所有错误都该重试。4xx（参数错、内容违规）重试也没用，只有**瞬时类**
（超时/限流/服务端 5xx）才重试；重试耗尽再 Fallback。

## 1. 组件设计

```
ResilientProvider（装饰器，实现 chat 契约）
  持有 [primary, fallback1, fallback2, ...] 一组候选
  for provider in candidates:
      for attempt in range(max_retries):
          try: return provider.chat(...)   # 成功即返回
          except RetryableError: 退避 sleep 后重试
          except FatalError: break         # 不可重试，直接换下一个候选
      # 该候选重试耗尽 → 进入下一个候选（Fallback）
  raise AllProvidersFailed                  # 全挂才报错
```

- **退避策略**：指数退避 + 抖动（`base * 2^attempt + random`），避免重试风暴。
- **错误分类**：`RetryableError`（超时/429/5xx）vs `FatalError`（4xx/参数/违规）——分类决定重试还是直接换。
- **归因**：回填 `usage.resilience = {attempts, fell_back_to, tried:[...]}`，可观测重试/降级路径。

## 2. 与 Router 的关系

Router 负责「正常时选哪个」，Fallback 负责「选中的挂了换哪个」。两种接法：

- **Router 出候选序列**：Router 按策略排序后给出 `[best, 2nd, 3rd]`，ResilientProvider 顺着降级。
- **ResilientProvider 包 Router**：每次失败让 Router 在**剩余健康池**里重选。后者更灵活
  （结合熔断，见 `circuit-breaker.md`）。

## 3. 成品长什么样（示意，非运行输出）

```
primary=premium-strong 注入 503：
  attempt1 → 503 → 退避 0.2s
  attempt2 → 503 → 退避 0.4s
  attempt3 → 503 → 重试耗尽 → Fallback
fallback=balanced-mid → 200 OK
usage.resilience = {attempts:3, fell_back_to:"balanced-mid", tried:["premium-strong","balanced-mid"]}
```

## 4. 踩过的坑 / 注意点

- **无脑重试所有错误**：4xx 重试纯浪费还放大延迟。必须按错误类型分可重试/不可重试。
- **重试无退避**：故障时齐刷刷重试 = 把下游打得更死（重试风暴）。指数退避 + 抖动。
- **Fallback 不留痕**：降级到便宜模型质量下降，不记录就查不出「为什么这条回答变差」。回填 resilience。
- **重试次数 × Fallback 数太大**：最坏延迟 = Σ(每候选重试耗时)，要设总超时预算封顶。
- **幂等性**：LLM chat 一般幂等（无副作用），但若带工具调用副作用，重试需去重/幂等键。

## 5. 面试问答（自测）

- **Q: Retry 和 Fallback 区别？** Retry 对同一 Provider 处理瞬时抖动；Fallback 换 Provider 处理整体不可用。
- **Q: 哪些错误该重试？** 只重试瞬时类（超时/429/5xx）；4xx（参数/违规）重试无用直接换或报错。
- **Q: 为什么要退避 + 抖动？** 防重试风暴——故障时同步重试会把下游打得更死。
- **Q: 最坏延迟怎么控？** 重试次数 × Fallback 数会放大延迟，需设总超时预算封顶。
- **Q: 和熔断的关系？** 熔断避免对已知挂掉的 Provider 反复重试（见 circuit-breaker.md）。

## 参考

- 组合位置：`ResilientProvider(ModelRouter(...))` 或 Router 出候选序列
- 配套：`circuit-breaker.md`（熔断防止对死掉的 Provider 持续重试）
