# Agent Loop 本质与 ReAct 落地

> 所属模块：04 · Agent 架构 ｜ 学习日期：2026-07-17  
> 实验：`experiments/mini-agent/agent_demo.py`（Loop / Memory / Plan / Tool / Multi-Agent 全绿）

## 一句话总结

Agent ≠ 多聊几句的 LLM，而是 **Observation → Think → Act(Tool) → Observation** 的闭环；停止靠 `finish` 或 `max_turns`，Observation **必须工具回填**，禁止模型伪造。

## 我的理解

```
        ┌──────────────────────────────────────┐
        ▼                                      │
   Observation ──▶ Think(LLM) ──▶ Act(Tool) ───┤
        ▲                                      │
        └──────── Reflection / 停止判断 ◀──────┘
              finish → 交付答案
              max_turns → 强制停（防死循环）
```

| 普通 LLM 调用                   | Agent              |
| --------------------------- | ------------------ |
| 一次 messages → 一次 completion | 多轮：中间穿插工具结果        |
| 知识截止于训练/上下文                 | 可访问外部世界（API/DB/文件） |
| 错了只能用户再问                    | 可自观察、重试、换工具        |

### ReAct 协议（文本版，教学友好）

```
Thought: 当前思考
Action: <tool_name | finish>
Action Input: <JSON>
# 系统写入：
Observation: <工具返回 JSON>
```

生产可换成原生 Function Calling，**语义不变**：模型出 name+arguments，宿主执行，结果回填。

### 防死循环三板斧

1. **max_turns**：硬上限（实验里坏 policy 3 步强制停）。
2. **finish 动作**：显式结束，答案进 `Action Input.answer`。
3. **非法 Action / 重复 Action 熔断**（P3 再加）：同工具同参连打 N 次 → 升级或停。

## 动手记录

退货题「订单 8821 耳机坏了能退吗？」轨迹：

1. `get_logistics` → 已签收 2026-07-12  
2. `calc_days_since` → 3 天  
3. `get_refund_policy` → 7 天窗口  
4. `finish` → **可退**（并读到 Long Memory 的 VIP / 开箱视频事实）

坏 policy 只调物流：`stopped_reason=max_turns`，步数=3。

## 面试问答

- **Q: Agent 和普通 LLM 调用的本质区别？**  
  A: 有没有 **工具闭环与停止条件**；Agent 能改外部状态/读外部事实，并在环内自我修正。
- **Q: 怎么防止死循环？**  
  A: max_turns + 显式 finish +（工程）重复动作检测 / 预算熔断。

## 参考

- ReAct 论文（Yao et al.）
- 模块 02 `reasoning-enhancement.md` / `prompts/react-agent.v1.md`（协议源头）
