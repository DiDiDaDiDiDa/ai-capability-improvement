# P3 · Mini Coding Agent

> 预计 25h ｜ 串联模块 02 / 03 / 04 / 06 ｜ 含金量最高

## 目标

写一个 mini Claude Code：能读文件、搜索、修改、执行、总结、给出 git commit 建议。这个项目把 Prompt、RAG、Agent、Tool Calling、Gateway 全部串起来，是未来一年面试价值最高的项目。

> 动手前先读 [Coding Agent Harness 拆解](harness-breakdown.md)：Claude Code / Cursor / Aider / OpenHands 各自 harness 怎么设计、有什么值得偷师的点，并映射到下面的里程碑。

## 怎么跑（当前验收）

```bash
cd projects/p3-mini-coding-agent && python3 app.py
# DONE · P3 M1+M2 green  EXIT:0
```

- **Mock policy** 离线全绿（教学 LLM 可热替换）
- 每次跑在 **temp 沙箱副本** 上改文件，不污染 `sandbox/sample_repo` 模板
- 工具：`list_dir` / `read_file` / `search_code` / `edit_file` / `run_cmd`

## 核心能力（七大模块）

- [ ] Repository Understanding：代码仓库理解（可用 RAG）— M4
- [x] Planner：任务规划与分解 — Mock policy 路径即最小 plan；完整 Plan-and-Execute 见模块 04
- [x] Tool Manager：Read / Write / Search / Run — `p3agent/tools.py`
- [x] File Edit：精确编辑文件 — 唯一 `old_str` 匹配（Aider 风格）
- [x] Build / Test：自动执行构建与测试 — `run_cmd` allowlist + `test_calc.py`
- [x] Self-Reflection：错误分析与自我修复 — 红测 → edit → 再跑（轻量 M3）
- [x] Retry / Finish：重试或结束的决策 — `finish` + `max_turns`
- [x] Git Commit 建议 — finish 附带 `commit_message`
- [ ] MCP 工具扩展 — M5

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

1. **M1 最小 Agent Loop** ✅：LLM + Read/Search 工具 + ReAct 循环（复用模块 04 骨架，换 Tool 注册表）
2. **M2 File Edit + Run** ✅：能改文件、跑命令、看结果
3. **M3 Reflection + Retry** 🟡：构建/测试失败时自我诊断重试（本验收已含「红→改→绿」；通用 reflection policy 待加深）
4. **M4 Repository Understanding**：用 RAG 理解大仓库（复用 P1 能力）
5. **M5 收尾**：Git Commit 建议（已有最小版）+ MCP 扩展 + 接 Gateway

## 目录

```
p3-mini-coding-agent/
  app.py                 # 验收入口 EXIT:0
  p3agent/
    workspace.py         # 路径沙箱
    tools.py             # read/search/edit/run/list
    loop.py              # ReAct + max_turns
    policy.py            # Mock policy（可热替换真 LLM）
  sandbox/sample_repo/   # 有意写错的 calc.add + unittest
  harness-breakdown.md
```

## 安全提示

Coding Agent 会执行命令和改文件，务必：

- 限制可执行命令范围（本实现仅 `python`/`python3`），破坏性操作（删除、force push）需确认
- 在隔离环境 / worktree / **temp sandbox 副本** 中运行
- 对外部输入（文件内容、命令输出）当作不可信数据处理
- 路径必须 resolve 在 workspace root 内（`../` 逃逸 → `path_error`）

## 验收标准

- [x] 给一个真实小仓库 + 一个任务，Agent 能读懂、改代码、跑测试、自我修复并给出 commit 建议（`app.py` 全绿）
- [ ] 大仓库 RAG 理解（M4）
- [ ] MCP + Gateway（M5）

## 底层逻辑（三句话）

1. **Coding Agent = 模块 04 Loop + 正交工具集**，不是另起炉灶的「智能 IDE」。
2. **工具少而正交**：read/search/edit/run；编辑用结构化替换，执行用白名单。
3. **安全是 harness 的一等公民**：沙箱路径 + 命令 allowlist + max_turns，和能力一起交付。
