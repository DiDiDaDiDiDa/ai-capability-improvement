# P3 · Mini Coding Agent

> 预计 25h ｜ 串联模块 02 / 03 / 04 / 06 ｜ 含金量最高

## 目标

写一个 mini Claude Code：能读文件、搜索、修改、执行、总结、给出 git commit 建议。这个项目把 Prompt、RAG、Agent、Tool Calling、Gateway 全部串起来，是未来一年面试价值最高的项目。

> 动手前先读 [Coding Agent Harness 拆解](harness-breakdown.md)：Claude Code / Cursor / Aider / OpenHands 各自 harness 怎么设计、有什么值得偷师的点，并映射到下面的里程碑。

## 核心能力（七大模块）

- [ ] Repository Understanding：代码仓库理解（可用 RAG）
- [ ] Planner：任务规划与分解
- [ ] Tool Manager：Read / Write / Search / Run
- [ ] File Edit：精确编辑文件
- [ ] Build / Test：自动执行构建与测试
- [ ] Self-Reflection：错误分析与自我修复
- [ ] Retry / Finish：重试或结束的决策
- [ ] Git Commit 建议
- [ ] MCP 工具扩展

## 目标架构

```
            User
              │
           Planner
              │
   ┌──────────┴──────────┐
   │                     │
Repository            Tool Manager
Understanding             │
   │              Read / Write / Search
   └──────────┬──────────┘
              │
           File Edit
              │
         Build / Test
              │
        Self Reflection
              │
         Retry / Finish
```

## 建议里程碑

1. **M1 最小 Agent Loop**：LLM + Read/Search 工具 + ReAct 循环（复用模块 04 的 Mini Agent）
2. **M2 File Edit + Run**：能改文件、跑命令、看结果
3. **M3 Reflection + Retry**：构建/测试失败时自我诊断重试
4. **M4 Repository Understanding**：用 RAG 理解大仓库（复用 P1 能力）
5. **M5 收尾**：Git Commit 建议 + MCP 扩展 + 接 Gateway

## 安全提示

Coding Agent 会执行命令和改文件，务必：
- 限制可执行命令范围，破坏性操作（删除、force push）需确认
- 在隔离环境 / worktree 中运行
- 对外部输入（文件内容、命令输出）当作不可信数据处理

## 验收标准

- 给一个真实小仓库 + 一个任务，Agent 能读懂、改代码、跑测试、自我修复并给出 commit 建议
