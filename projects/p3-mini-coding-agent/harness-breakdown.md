# 主流 Coding Agent 的 Harness 拆解

> 配套 P3。造 mini coding agent 前，先看清 Claude Code / Cursor / Aider / OpenHands 各自的 harness 是怎么设计的——它们用的是同一批底座模型，差异几乎全在 harness 与 loop 这两层（见 [模块 00](../../docs/00-key-concepts/)）。

## Coding Agent 的通用骨架

所有 coding agent 本质都是这个循环，区别在每一环怎么实现：

```
      用户任务
         │
   ┌─────▼─────┐
   │  上下文构建 │  ← 仓库理解 / 检索 / 打开的文件 / 历史
   └─────┬─────┘
         │
   ┌─────▼─────┐
   │  LLM 决策  │  ← 决定下一步：读?改?跑?问?结束?
   └─────┬─────┘
         │
   ┌─────▼─────┐
   │  工具执行  │  ← Read / Search / Edit / Run / Git
   └─────┬─────┘
         │
   ┌─────▼─────┐
   │  结果观察  │  ← 编译/测试/报错回喂
   └─────┬─────┘
         │
     验证通过? ──否──▶ 反思 / 重试（回到决策）
         │是
       结束 / commit 建议
```

## 四家对比

| 维度 | Claude Code | Cursor | Aider | OpenHands |
|------|-------------|--------|-------|-----------|
| 形态 | 终端 CLI / SDK | IDE（VSCode 分支）| 终端 CLI | 开源平台（Web+沙箱）|
| 上下文构建 | Agentic 搜索（少预索引）| 仓库预索引 + 语义检索 | repo map（tree-sitter 摘要）| 文件浏览 + 检索 |
| 编辑方式 | 工具调用改文件 | 内联 diff / 补全 | diff / whole-file 编辑格式 | 工具调用 + 编辑器 |
| 执行环境 | 本地 shell（带权限）| 本地 | 本地 + git | Docker 沙箱 |
| 循环控制 | 自主多步 + 子 agent | 半自主（人在环）| 编辑-测试循环 | 全自主 agent 循环 |
| 扩展 | MCP / Skills / Hooks | 规则文件 / MCP | 约定 | 可插拔 agent |
| 定位 | 通用 agent 化编码 | 沉浸式 IDE 编码 | 轻量结对 | 研究/自动化基线 |

> 结论：**同一个 Claude/GPT 模型，套不同 harness，能力体感差别巨大。** 差异集中在"上下文怎么给、编辑怎么落、循环谁做主"。

## 各家值得偷师的点

### Claude Code —— agentic 搜索 + 精简上下文
- 不做重预索引，靠模型主动 `grep`/读文件按需拉上下文（省索引维护，靠强模型）
- 工具集小而正交：Read/Edit/Bash/Grep/Glob
- 用 Skills 打包重复流程、Hooks 插入确定性动作
- **偷师点**：工具设计"少而正交"，上下文"按需拉取"而非一次塞满

### Cursor —— 预索引 + 人在环 diff
- 仓库预先切块+embedding，语义检索相关代码
- 改动以 inline diff 呈现，人工 accept/reject
- **偷师点**：预索引适合大仓库冷启动；人在环 diff 是高危编辑的安全阀

### Aider —— repo map 与编辑格式
- 用 tree-sitter 生成"仓库地图"（符号摘要）压进上下文，省 token
- 定义严格的编辑返回格式（diff / whole-file），保证可解析、可应用
- 每次编辑后自动 git commit，天然可回滚
- **偷师点**：repo map 是"低成本仓库理解"的好范式；结构化编辑格式是稳定落盘的关键

### OpenHands —— 沙箱 + 全自主循环
- 所有执行在 Docker 沙箱，安全隔离
- 完整自主 agent 循环，可跑 SWE-bench 类基准
- **偷师点**：沙箱化执行 + 可评测，是工程化和安全的标杆

## 映射到 P3 里程碑

| P3 里程碑 | 借鉴对象 |
|-----------|---------|
| M1 最小 Loop（Read/Search + ReAct）| Claude Code 的精简工具集 |
| M2 File Edit + Run | Aider 的结构化编辑格式 + 自动 commit |
| M3 Reflection + Retry | OpenHands 的自主循环 + 测试回喂 |
| M4 Repository Understanding | Aider repo map / Cursor 预索引二选一 |
| M5 收尾（MCP / Gateway）| Claude Code 的 MCP + Skills 扩展 |

## 面试高频题
1. Coding agent 的核心循环是什么？每一环干嘛？
2. Claude Code 的 agentic 搜索和 Cursor 的预索引各有什么优劣？
3. 为什么 Aider 要定义严格的编辑返回格式？不定义会怎样？
4. 为什么执行要放沙箱？本地跑有什么风险？
5. 同样的模型，为什么不同 coding agent 体验差很多？（答：harness/loop 层的差异）
