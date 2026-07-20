# 模块 04 · Agent 核心架构三要素

> 预计 20h ｜ 对应学习方案第四阶段 ｜ 支撑项目 P3

## 学习目标

理解 Agent 的本质循环，掌握 Memory / Planning / Tool 三要素，能搭出一个可运行的 Mini Agent，并理解多智能体协同的常见拓扑。

## 核心公式与循环

```
Agent = LLM + Memory + Planning + Tool + Observation + Reflection

        ┌──────────────────────────────────────┐
        ▼                                        │
    Observation ──▶ Think(LLM) ──▶ Plan ──▶ Act(Tool)
        ▲                                        │
        └──────────── Reflection ◀───────────────┘
                 (成功则结束 / 失败则重试 / max_turns 停)
```

## 核心概念清单

### 1. Agent Loop 本质
- ReAct 循环：Reason → Act → Observe
- 何时停止、如何避免死循环
- Observation 的组织与截断

### 2. Memory（记忆）
- Short-term Memory：对话上下文窗口
- Long-term Memory：持久化、跨会话
- Vector Memory：语义检索历史
- 记忆的写入策略与召回策略

### 3. Planning（规划）
- Task → SubTask 分解
- 执行顺序、依赖管理
- Retry / 错误恢复
- Plan-and-Execute vs ReAct 的取舍

### 4. Tool（工具）与能力供给
- JSON Schema 定义工具
- Function Calling 机制
- **MCP（Model Context Protocol）**：工具/数据的标准协议（详见 [模块 00](../00-key-concepts/)）
- **Skills**：流程与资源打包，渐进式披露（详见 [模块 00](../00-key-concepts/)）
- OpenAPI / 外部 API 接入

### 4.5 工程分层（贯穿概念）
- Prompt / Context / Harness / Loop Engineering 四层递进，Agent 工程主战场在 Harness 与 Loop（详见 [模块 00](../00-key-concepts/)）

### 5. Workflow 编排
- Sequential / Parallel / Router / Loop
- 何时用固定 workflow，何时用自主 agent

### 6. 多智能体系统
- Supervisor-Worker
- Planner-Executor
- 多 agent 协同的通信与状态共享
- 什么时候多 agent 反而更差（协调开销）

## 建议产出物

- [x] 一个 Mini Agent：工具调用 + ReAct 循环（`experiments/mini-agent/`；P3 M1 起点；真 LLM 可热替换 policy）
- [x] P3 换 Tool 注册表：`projects/p3-mini-coding-agent/`（read/search/edit/run + 沙箱；`python3 app.py` 全绿）
- [x] 三种记忆（short/long/vector）的最小实现（同实验第 2 段）
- [x] 一个 Supervisor-Worker 多 agent demo（同实验第 5 段）

## 笔记与实验

| 主题 | 笔记 | 实验断言要点 |
|------|------|----------------|
| Loop / ReAct | [`agent-loop.md`](agent-loop.md) | 8821 可退四步；max_turns 强制停 |
| Memory / Plan / Tool / 多 Agent | [`memory-planning-tools.md`](memory-planning-tools.md) | 三记忆；Plan vs ReAct；Schema 校验；路由 |

```bash
cd experiments/mini-agent && python3 agent_demo.py
```

## 面试高频题（出口自测）

1. Agent 和普通 LLM 调用的本质区别是什么？
2. ReAct 循环包含哪些步骤？怎么防止死循环？
3. Short / Long / Vector Memory 分别怎么用？
4. Plan-and-Execute 和 ReAct 各适合什么任务？
5. Function Calling 的完整流程？模型是怎么"调用"工具的？
6. MCP 解决了什么问题？
7. 多 agent 一定比单 agent 好吗？什么时候不该用？

## 资源

- ReAct 论文
- OpenAI Agents SDK / Anthropic 构建 Agent 的工程实践
- MCP 官方规范
- LangGraph / AutoGen 架构文档（看设计思想）
- 模块 02：`reasoning-enhancement.md`、`prompts/react-agent.v1.md`

## 检查清单

- [x] 能默画 Agent 循环并解释每一步（`agent-loop.md`）
- [x] 搭出可运行的 Mini Agent（`experiments/mini-agent/agent_demo.py`）
- [x] 能讲清三种记忆与多 agent 拓扑（`memory-planning-tools.md`）
- [x] 能回答上面全部面试题（对照笔记 + 实验轨迹）
