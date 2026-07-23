# Memory · Planning · Tool · 多智能体

> 所属模块：04 · Agent 架构 ｜ 学习日期：2026-07-17  
> 实验：`experiments/mini-agent/agent_demo.py`

## 一句话总结

三要素分工：**Memory 管上下文与跨会话，Planning 管任务怎么拆，Tool 管能对世界做什么**；多智能体是拓扑选择，不是默认更强。

## Memory 三种

| 类型     | 形态         | 写入        | 召回       | 实验抓手                          |
| ------ | ---------- | --------- | -------- | ----------------------------- |
| Short  | 滑动窗口 turns | 每步 append | 最近 N 轮   | `ShortMemory(max_turns=3)` 截断 |
| Long   | KV 持久      | 显式 put    | key / 前缀 | VIP、开箱视频事实                    |
| Vector | 向量索引       | add 摘要    | 语义 top-k | 查询「8821 退货」命中 m1              |

**选型**：对话连贯 → Short；用户偏好/账号事实 → Long；「上次类似工单」→ Vector。三者可叠加（ReAct 答退货时读了 Long + 写了 Vector 轨迹）。

## Planning：Plan-and-Execute vs ReAct

|     | ReAct                | Plan-and-Execute   |
| --- | -------------------- | ------------------ |
| 顺序  | 边观察边决定下一步            | 先拆 SubTask，再按依赖执行  |
| 适合  | 分支多、信息逐步揭露           | 依赖清晰、可批处理          |
| 代价  | 步数不可完全预知             | 规划错了后面全歪，需 Retry   |
| 实验  | 8821 四步可退；9001 未签收早停 | 同题 DAG：t1→t2/t3→t4 |

```
Plan:  t1 查物流 ─┬─▶ t2 算天数 ─┐
                 └─▶ t3 查政策 ─┴─▶ t4 汇总
```

依赖未满足的任务 `skipped`；工具失败可 `max_retries`（实验默认 1）。

## Tool 与 Function Calling

1. **注册表**：name + description + JSON Schema + handler。  
2. **模型侧**：只生成 `{name, arguments}`（或文本协议 Action）。  
3. **宿主侧**：校验 required → 执行 → 返回 Observation。  
4. **永不让模型自己写 Observation**（否则幻觉闭环）。

实验工具：`get_logistics` / `get_refund_policy` / `calc_days_since` / `search_kb`。  
缺参 → `invalid_args`；未知工具 → `unknown_tool`。

MCP / Skills：标准协议与流程打包见模块 00；本层先把「注册-校验-分发」跑通，P3 再挂真实 MCP。

## 多智能体拓扑

实验：**Supervisor-Worker**

| 用户问   | 路由              | Workers               |
| ----- | --------------- | --------------------- |
| 订单到哪了 | logistics       | 单兵                    |
| 退货政策  | refund_pipeline | logistics + policy 串联 |
| 你好    | chitchat        | 单兵（避免协调税）             |

**多 agent 不该用时**：单步可答、无专业分工、延迟预算紧——协调与汇总本身吃 token。

其他拓扑（笔记级）：Planner-Executor（规划者与执行者分离）、并行 fan-out 再 merge。

## 与 P3 的桥

```
不变：Thought→Action→Obs 循环 + max_turns + Memory
变化：Tool 注册表 → read_file / search_code / run_tests / edit / finish
```

模块 04 Mini Agent 是 P3 M1 的直接起点。

## 面试问答

- **Q: Short/Long/Vector 怎么用？** 见上表。  
- **Q: Plan-and-Execute vs ReAct？** 依赖清晰用 Plan；动态分支用 ReAct。  
- **Q: Function Calling 流程？** Schema → 模型选工具 → 宿主执行 → 回填 → 再推理。  
- **Q: 多 agent 一定更好吗？** 否，有协调开销；简单题单 agent 更稳。
