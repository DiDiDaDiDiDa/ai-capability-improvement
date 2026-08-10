# Observability 设计说明：Tracing + Metrics

> 所属项目：P2 · AI Gateway ｜ 对应模块 06 ｜ 状态：**已落代码**
> （实现 `p2gateway/observability.py`，验收 `app.py` 第 21 段；全栈 8 层咬合见第 22 段）

## 一句话总结

可观测性回答三个问题：**Tracing**「这一个请求经过了哪些环节、各花多久」、**Metrics**
「整体的量/延迟/错误/成本趋势」、**Logging**「出事时能翻到细节」。Gateway 是天然的
汇聚点——所有请求都过它，埋一层就全链路可见。

## 0. 三大支柱各管什么

| 支柱          | 回答       | 数据形态                 | 例子                                             |
| ----------- | -------- | -------------------- | ---------------------------------------------- |
| **Tracing** | 单请求的调用链路 | span 树（parent/child） | guardrail→ratelimit→cache→router→provider 各段耗时 |
| **Metrics** | 整体聚合趋势   | 时序数值                 | QPS、p95 延迟、错误率、$/min、缓存命中率                     |
| **Logging** | 具体细节     | 结构化日志                | 某请求的 request_id、命中规则、错误堆栈                      |

三者用 **request_id / trace_id** 串起来：Metrics 报警 → 按 trace_id 下钻到 Trace → 翻 Log 看细节。

## 1. Tracing：一次请求的 span 树

```
trace_id=abc123
  span: gateway.request                (总 1240ms)
    ├ span: guardrail.input            (5ms)
    ├ span: ratelimit.check            (1ms)
    ├ span: cache.lookup               (3ms, miss)
    ├ span: router.select              (2ms, chosen=premium-strong)
    ├ span: provider.chat              (1220ms)  ← 瓶颈一眼可见
    └ span: guardrail.output           (9ms)
```

每层装饰器开一个 span，记 `name/start/duration/attributes`（如 provider、cache_status、
version_tag）。span 树让「这个请求为什么慢」可定位——本设计里每个 `XxxProvider` 装饰器
在 `chat` 前后打点，父子 span 靠 trace 上下文串联。

## 2. Metrics：聚合趋势

按维度打点，供报警和看板：

| 指标 | 类型 | 维度 |
|------|------|------|
| 请求数 / QPS | counter | provider, version, status |
| 延迟 p50/p95/p99 | histogram | provider |
| 错误率 | counter | error_type, provider |
| 成本 $/min | counter | provider, version（复用 Cost Dashboard）|
| 缓存命中率 | gauge | — |
| 熔断状态 | gauge | provider |

**用分位数不用均值**：p95/p99 才反映尾延迟体感；均值会被拉平掩盖长尾。

## 3. 组件设计

```
TracedProvider（装饰器）
  chat(messages):
    span = tracer.start("provider.chat", trace_id, attrs={...})
    t0 = now()
    try:
        resp = inner.chat(...)
        span.ok(); return resp
    except Exception: span.error(); raise
    finally:
        span.duration = now()-t0
        metrics.observe("latency_ms", span.duration, labels)
        metrics.inc("requests", labels)
        usage["trace"] = {"trace_id", "spans":[...]}   # 回填便于调试
```

- **贯穿全链路**：每个装饰器层各开 span，共享 trace_id → 完整链路视图。
- **复用已有 usage**：cost/cache/routing/version_tag 直接进 metrics labels 和 span attrs，不重采。
- **request_id 打进日志**：Trace/Metric/Log 靠同一个 id 关联下钻。

## 4. 成品长什么样（示意，非运行输出）

```
[Metrics 快照]
 QPS 42 | p95 延迟 1180ms | 错误率 1.2% | $/min 0.08 | 命中率 28.6%
 by provider: premium(p95=1200ms,err=3%) balanced(p95=520ms) cheap(p95=210ms)

[Trace 单请求 abc123] 总 1240ms
 guardrail.input 5 | cache.lookup 3(miss) | router 2 | provider.chat 1220 | guardrail.output 9
 → 瓶颈: provider.chat 占 98%
```

## 5. 诚实说明：这是最小内核

教学实现是**进程内**的 span/metric 收集 + 文本渲染。生产可观测性是一套基础设施：

- **Tracing**：OpenTelemetry SDK → Jaeger / Tempo，跨服务传播 trace context。
- **Metrics**：Prometheus 拉取 / OTLP 推送 → Grafana 看板 + 告警规则。
- **Logging**：结构化日志 → Loki / ELK，按 trace_id 检索。

本设计给出的是「**在 Gateway 每层埋点、用 trace_id 串联、复用 usage 做 labels**」这套
方法内核，不是完整平台——**不能声称这就是生产级可观测性**，它是接入 OTel/Prometheus 前的骨架。

## 6. 踩过的坑 / 注意点

- **只有 Metrics 没有 Tracing**：知道「整体变慢了」但定位不到「哪个请求的哪一环」。要能下钻。
- **延迟只报均值**：长尾被掩盖，p95/p99 才是体感。用 histogram。
- **三支柱不关联**：Trace/Metric/Log 各存各的，出事串不起来。必须统一 trace_id/request_id。
- **埋点采全量**：高 QPS 下全量 trace 成本高，生产用采样（如 1%）+ 错误请求必采。
- **敏感信息进 trace**：span attributes / 日志里别塞 prompt 明文或 PII（与 Guardrail 呼应）。

## 7. 面试问答（自测）

- **Q: 可观测性三大支柱？** Tracing（单请求链路）、Metrics（聚合趋势）、Logging（细节）；用 trace_id 串联。
- **Q: 为什么 Gateway 适合做观测点？** 所有请求都过它，埋一层即全链路可见，且能复用 usage 里已有信号。
- **Q: 延迟为什么看分位数？** p95/p99 反映尾延迟体感，均值会掩盖长尾。
- **Q: 高 QPS 下 trace 怎么办？** 采样（如 1%）+ 错误请求必采，平衡成本与可观测。
- **Q: 观测里要注意什么安全？** span/日志别塞 prompt 明文或 PII。

## 参考

- 组合位置：`TracedProvider` 包最外层（或每层各开 span 共享 trace_id）
- 生产栈：OpenTelemetry + Jaeger/Tempo + Prometheus + Grafana + Loki
- 复用：`cost-dashboard.md`（成本指标直接进 metrics）
