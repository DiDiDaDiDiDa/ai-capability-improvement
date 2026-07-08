# 实例辨析：Colima 里跑的一堆 MCP 容器，是 Client 还是 Server？

> 所属模块：00 关键概念 ｜ 学习日期：2026-07-07
> 一个来自真实场景的问答，用来把 MCP 的 Client / Server 角色彻底分清。

## 问题

> 我 Colima 下面有好多容器在运行中，都是 MCP。它们是 mcp-client 还是 mcp-server？为什么需要它们？MCP 不是只是一个协议吗？

## 一句话结论

**你 Colima 里跑的那些容器，是 MCP Server，不是 Client。**

MCP 确实"只是一个协议"，但协议是"约定怎么对话"，真正跑起来必须有**两个角色**在对话——就像 HTTP 是协议，你得有浏览器（Client）和网站服务器（Server）两端。MCP 也分 Client 和 Server。

## 怎么判断谁是谁

**谁提供能力，谁就是 Server；谁使用能力（内嵌在 AI 应用里），谁就是 Client。**

```
┌─────────────────────────────┐         ┌──────────────────────────┐
│  Host（AI 应用）             │         │  你 Colima 里的容器        │
│  Claude Desktop / Cursor /  │         │                          │
│  Claude Code ...            │         │  MCP Server A（如查数据库）│
│                             │  MCP    │  MCP Server B（如读文件） │
│   ┌──────────────┐          │ 协议对话 │  MCP Server C（如调 API） │
│   │ MCP Client A │◀────────────────▶ │  ...                     │
│   │ MCP Client B │◀────────────────▶ │  每个容器 = 一个 Server  │
│   │ MCP Client C │◀────────────────▶ │                          │
│   └──────────────┘          │         │                          │
└─────────────────────────────┘         └──────────────────────────┘
     Client 内嵌在 AI 应用里              Server 是独立进程/容器
```

- **MCP Client**：不是独立容器，它是**内嵌在 AI 应用（Host）里**的一段逻辑。打开 Claude Desktop / Cursor，它内部会为每个 Server 起一个 Client，一对一连接。
- **MCP Server**：就是 Colima 里那些容器。每个 Server 是**独立进程**，专门对外暴露某类能力（Tools / Resources / Prompts）。

## 为什么需要它们（既然只是协议）

协议只是"接口标准"，能力得有人实现。这些 Server 就是**能力的实现体**：

- `mcp-server-postgres` 容器 → 让 AI 能查数据库
- `mcp-server-filesystem` 容器 → 让 AI 能读本地文件
- `mcp-server-github` 容器 → 让 AI 能操作仓库

没有这些 Server，AI 应用光有 Client（会说 MCP 协议）也没用——就像浏览器再强，没有网站服务器也打不开任何页面。

## 为什么拆成独立容器（而不是塞进 AI 应用里）

这正是 MCP 解决"M×N 集成爆炸"的方式：

1. **解耦**：各工具独立，一个挂了不影响其他，也不影响主应用。
2. **复用**：同一个 Server，Claude Desktop、Cursor、自写 Agent 都能连——写一次，到处用。
3. **隔离/安全**：容器化跑，权限可控。查数据库的 Server 拿不到文件系统权限。
4. **语言无关**：Server 用 Python/Go/Node 都行，只要说 MCP 协议，Client 就能连。

## 记忆锚点

> **MCP = 协议（规范）；Client = AI 应用里"会说这个协议的嘴"；Server = 那些"提供具体能力的容器"。**
> 协议是死的，Client / Server 是活的两端，缺一端就跑不起来。

## 关联

- 概念总览见 [模块 00 README](README.md) 的 MCP 一节
- Tool Calling 与 MCP 三原语在 [模块 04 · Agent](../04-agent-architecture/) 深入
