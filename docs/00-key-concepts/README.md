# 模块 00 · 关键概念速览（Agent 时代必备词汇）

> 跨模块前置阅读。这里集中解释那些在各模块里反复出现、但单独拎出来才好理解的"Agent 时代"核心概念：MCP、Skills，以及 Prompt / Context / Harness / Loop 四层 engineering。

先建立一个总认知：这些词分两组——
- **给模型供给能力**：MCP（连接外部工具/数据）、Skills（打包做事的流程与知识）
- **围着模型做工程**：Prompt → Context → Harness → Loop，四层同心圆，作用域逐层放大

---

## 一、MCP（Model Context Protocol）

Anthropic 于 2024 年底提出的**开放协议**，被称为"AI 应用的 USB-C 接口"。

### 解决什么问题
M 个 AI 应用要接 N 个工具/数据源，没有标准就得写 M×N 套定制胶水代码。MCP 提供统一协议，把它降成 M+N。

### 架构与三种原语
```
Host（Claude Code / Desktop 等）
  └─ MCP Client ──1:1── MCP Server ──▶ 工具 / 数据源
```
Server 向模型暴露三类能力：
- **Tools**：模型可调用的函数（模型主导，如"查数据库""发请求"）
- **Resources**：可读入上下文的数据（应用主导，如文件、记录）
- **Prompts**：可复用的提示词模板（用户主导）

传输方式：`stdio`（本地进程）、Streamable HTTP / SSE（远程）。

### 一句话
**MCP 是"连接层"——让 Agent 够得到外部世界。**

---

## 二、Skills（Agent Skills）

Anthropic 2025 年推出的**能力打包机制**。一个 Skill = 一个文件夹：
- `SKILL.md`：YAML 头（`name` + `description`）+ 正文（操作指令）
- 可选：脚本、模板、参考资料等附件

### 核心机制：渐进式披露（Progressive Disclosure）
- 平时上下文里**只有** skill 的名字 + 描述（占用极小，可常驻）
- 任务匹配上了，才加载完整 `SKILL.md`
- 里面引用的脚本/附件，用到时再读

好处：几十上百个 skill 也不会撑爆上下文窗口。

### 一句话
**Skills 是"知识/流程层"——告诉 Agent 怎么把某一类任务干好。**

### MCP vs Skills（高频对比）
| | MCP | Skills |
|---|-----|--------|
| 提供什么 | 对外部系统的**连接/工具** | 做事的**流程与 know-how** |
| 类比 | 给 Agent 一双"手" | 给 Agent 一本"操作手册" |
| 载体 | 协议 + Server | 文件夹 + SKILL.md |
| 关系 | Skill 内部可以调用 MCP 工具 | — |

---

## 三、四层 Engineering（同心圆递进）

```
┌─ Loop Engineering ─ 编排 agent 循环 ──────────────┐
│ ┌─ Harness Engineering ─ 模型外整个脚手架 ──────┐ │
│ │ ┌─ Context Engineering ─ 管理整个上下文窗口 ┐ │ │
│ │ │ ┌─ Prompt Engineering ─ 单次调用措辞 ─┐  │ │ │
│ │ │ └──────────────────────────────────────┘  │ │ │
│ │ └────────────────────────────────────────────┘ │ │
│ └──────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
作用域：Prompt ⊂ Context ⊂ Harness ⊂ Loop
```

### 1. Prompt Engineering
优化**单次调用**的输入措辞——"这一句指令怎么写"。作用域 = 一条消息。详见模块 02。

### 2. Context Engineering
优化**整个上下文窗口**里的内容：系统提示 + 工具定义 + 检索片段 + 记忆 + 历史对话。
- 核心认知：**上下文是有限且会衰减的资源**（越长越容易"迷失在中间"、越贵、越慢）
- 要主动决定：放什么、检索什么、压缩什么、丢什么、什么时候写进长期记忆
- Agent 一旦变成多轮，瓶颈就从"写好一句 prompt"转移到"每一轮窗口里到底装什么"

### 3. Harness Engineering
优化模型**外部的整个软件脚手架**：系统提示、工具集、编排代码、上下文管理、护栏（guardrail）、输出解析。
- Claude Code、Cursor 本质就是一套 harness
- 同样的底座模型，harness 做得好坏直接决定产品体验——差异化很多在这层

### 4. Loop Engineering
优化 Agent 的**循环控制流**：`gather context → take action → verify work → repeat`。
- 关注：迭代节奏、停止条件、重试 / 反思（reflection）、工具结果如何回喂、要不要派生子 Agent
- 可看作 harness 中专注"控制流"的那部分

### 一句话串起来
**从 Prompt 到 Loop，是从"写好一句话"一路走到"把模型做成一个能自主干活的产品"。** 越往外层，越是 AI Infra / Agent 工程的核心竞争力。

---

## 与各模块的关系

| 概念 | 主要展开于 |
|------|-----------|
| MCP、Tool Calling | 模块 04（Agent）、模块 06（Infra 接入）|
| Skills、Progressive Disclosure | 模块 04（Agent）|
| Prompt Engineering | 模块 02 |
| Context Engineering | 模块 02 / 03（RAG 即上下文供给）/ 04（Memory）|
| Harness / Loop Engineering | 模块 04（Agent 循环）、项目 P3 |

## 配套速查
- [术语大图谱](terminology-map.md)：一张"从模型到产品"的全景分层图 + 按问题定位术语的速查表。看不懂某个词时先回到那里定位它属于哪一层。
- [实例辨析：Colima 里的 MCP 容器是 Client 还是 Server？](mcp-client-vs-server.md)：用真实场景讲透 MCP 的 Client / Server 角色区分。
- [实例：本地 MCP 全链路是怎么串起来的](mcp-local-chain.md)：用本机 Codex + Colima 配置，走通"配置 → docker 拉起 Server → Server 连真实 Redis/ClickHouse/S3"整条链路。
- [完整标准 Skill 示例](skill-example.md)：一个结构完整、字段标准的 Skill（文件夹结构 + SKILL.md + 脚本 + 渐进式披露），照着就能自己写。

## 检查清单
- [x] 能用一句话分别说清 MCP 和 Skills，并讲出两者区别
- [x] 能说出 MCP 的三种原语（Tools / Resources / Prompts）
- [x] 能解释 Skills 的渐进式披露为什么重要
- [x] 能默画 Prompt ⊂ Context ⊂ Harness ⊂ Loop 的同心圆并解释每层作用域
- [x] 能举例说明什么问题该用 Context Engineering 而不是继续堆 Prompt
