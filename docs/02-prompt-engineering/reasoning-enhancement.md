# 推理增强：CoT / SC / ToT / ReAct / Reflection（Day 6）

> 所属模块：02 · 结构化提示词设计 ｜ 学习日期：2026-07-14

## 一句话总结

推理增强不是换模型，而是**改生成路径**：让模型先显式想（CoT）、多想几次投票（Self-Consistency）、分叉搜索（ToT）、边想边动手（ReAct）、想完再自检（Reflection）。选型看任务难度 × 延迟/成本预算。

## 我的理解

Day5 解决的是"prompt 怎么拼"。Day6 解决的是：**同一个模型，换推理路径，复杂题正确率能明显上去**——但每条路径都有 token 与延迟税。

```
任务难度 ↑
    │
    │  Reflection ── 生成后自检/改写（可叠在任意路径上）
    │       ▲
    │  ReAct ────── 推理 ⇄ 工具调用循环（需要外部世界）
    │       ▲
    │  ToT ──────── 多分支搜索 + 剪枝（最贵，最难的规划题）
    │       ▲
    │  Self-Consistency ── 同题多样本 + 投票（中等贵）
    │       ▲
    │  CoT ──────── 显式中间步骤（基线增强，几乎零改造成本）
    │       ▲
    │  直接答 ───── Zero-shot 一步出答案（便宜，复杂题易错）
    │
    └──────────────────────────────────────────▶ 成本 / 延迟
```

### 1. Chain-of-Thought（CoT）—— 让模型"把草稿纸露出来"

**问题**：直接问复杂算术/逻辑题，模型容易跳步、抄近路，答案错了还很自信。

**做法**：要求输出**中间推理步骤**，最后再给答案。经典触发句：
- Zero-shot CoT：`"Let's think step by step."` / `"请一步步推理，最后给出答案。"`
- Few-shot CoT：示例里写完整推理链，不只给最终标签

```
直接答:  问题 ──────────────────────────▶ 答案（容易跳步）

CoT:     问题 ─▶ 步骤1 ─▶ 步骤2 ─▶ … ─▶ 答案
                 └── 中间状态占上下文，也占注意力 ──┘
```

**为什么有效（工程直觉，不背论文）**：
1. **算力摊到多步**：每步只解一小块，比一步硬解整题稳
2. **中间状态可检**：人/程序能盯某一步是否错，而不只盯最终答案
3. **注意力可聚焦**：当前步只依赖前几步局部信息，降低"一步想全盘"的负担

**对小模型也有效吗？**  
大模型（能力足够）+ CoT 提升最明显。**太小的模型**可能"装模作样写步骤，步骤本身就错"——CoT 不能创造能力，只能释放已有能力。经验：小模型优先**更强的 few-shot / 工具**，别迷信一步步思考。

**落地写法**：
```
system: 你是严谨的解题助手。先写推理过程，最后一行输出：答案: <结果>
user: 问题：……
```
解析时用正则抓 `答案:` 后的字段；过程文本可落日志供人工抽检。

### 2. Self-Consistency（SC）—— 同一题多想几次再投票

**问题**：CoT 只走**一条**推理路径；路径选错就全错。

**做法**：
1. 同一 prompt，用 **temperature > 0** 采 N 条独立 CoT（常见 N=5~20）
2. 从每条轨迹抽出**最终答案**（忽略过程措辞差异）
3. **多数投票**（或加权）得到最终结果

```
          ┌─ CoT path1 → 答案 A ─┐
问题 ─▶  ─┼─ CoT path2 → 答案 B ─┼─ 投票 → 最终答案
          ├─ CoT path3 → 答案 A ─┤
          └─ CoT pathN → 答案 A ─┘
```

**代价**：延迟与费用近似 ×N（可并行打 API 压墙钟时间，但钱仍是 ×N）。  
**值得用的场景**：答案空间离散、可比对（数学结果、分类标签、是/否）；错误路径彼此分散、正确路径会反复出现。  
**不值得**：开放式写作、创意生成（没有"正确票"）；或 N 太大预算爆掉。

和 Day4 采样的关系：SC **故意**用中高温制造路径多样性；贪心/T→0 会让 N 条几乎相同，投票无意义。

### 3. Tree-of-Thought（ToT）—— 搜索式推理

**问题**：有的题不是一条链，而是**要探索多条局部方案**（规划、谜题、多步决策），线性 CoT 不会回溯。

**做法**（概念）：
1. 把"思考"拆成**节点**（一个中间状态/局部方案）
2. 每步**扩展**多个候选（branching factor b）
3. 用模型或规则**评估**节点好坏，剪掉差的
4. BFS/DFS/beam 在树上搜索，直到终态

```
              [问题]
             /  |  \
          s1   s2   s3      ← 第 1 层候选
         / \        |
       s11 s12     s31     ← 评估后剪掉 s12…
         |
       终态
```

**和 CoT / SC 的区别**：
| | CoT | SC | ToT |
|--|-----|----|-----|
| 结构 | 单链 | 多条独立链 | 树（可共享前缀、可回溯） |
| 评估 | 无（走到头） | 末端答案投票 | **中间节点**也可打分剪枝 |
| 成本 | 1× | N× | 通常 ≫ N×（宽×深） |
| 适用 | 多数中等推理 | 离散答案提稳 | 强规划/搜索题 |

工程上 ToT 很少"纯 prompt 手搓一棵树"就上生产——多半落成 **Agent 循环 + 状态存储 + 剪枝策略**。先懂思想：复杂决策 = 搜索，不是一条直线。

### 4. ReAct —— Reasoning + Acting 交替

**问题**：纯 CoT 只能在脑子里推；很多题需要**查资料、算数、调 API** 才能对。

**做法**：固定输出协议，在 **Thought / Action / Observation** 间循环：

```
Thought: 我需要订单 8821 的物流状态
Action: get_logistics(order_id="8821")
Observation: （外部工具返回）已发货，在途，预计明天到
Thought: 可以回答用户了
Action: finish
Answer: 您的包裹在途，预计明天送达
```

```
┌─────────┐   Thought    ┌─────────┐
│  LLM    │ ───────────▶ │  决定    │
│         │ ◀─────────── │  行动    │
└─────────┘  Observation └────┬────┘
     ▲                        │ Action
     │                        ▼
     │                  ┌──────────┐
     └──── 工具结果 ────│  Tool    │
                        └──────────┘
```

**和纯 CoT 的区别**：
- CoT：只在语言模型内部推，**无外部副作用**
- ReAct：**推理驱动行动**，行动结果再进入上下文，形成闭环
- 这就是模块 04 Agent 的最小内核：`while not done: think → act → observe`

**Prompt 要点**：
- 工具列表 + JSON/文本 schema 写死在 system
- 强制格式：`Thought:` / `Action:` / `Action Input:`，便于解析
- 规定 `finish` 或 `Final Answer` 作为终止
- **Observation 是工具真值**，不要让模型自己编 Observation（防幻觉闭环）

### 5. Reflection —— 生成后再自我批评

**问题**：一稿过的输出常有遗漏、格式错、逻辑洞。

**做法**（两段或三段）：
1. **Generate**：正常生成初稿（可叠加 CoT）
2. **Reflect**：用另一条 prompt（或同一模型换角色）批评初稿——缺什么、哪步错、是否违反约束
3. **Revise**：根据批评改写终稿

```
初稿 ─▶ 批评清单 ─▶ 终稿
         │
         └── 可限制只批"事实/格式/安全"，避免空泛"写得更好"
```

**性价比**：通常 **+1~2 次调用**，比 SC×10 / ToT 便宜，对写作、代码、长答案质量提升很香。  
**注意**：Reflection 也会幻觉——批评本身可能错；关键场景仍要 schema 校验 / 单测 / 人工抽检。可把 Reflection 做成**可开关中间件**，叠在 CoT 或 ReAct 终态之后。

### 6. 怎么选？（工程决策表）

| 场景 | 优先策略 | 原因 |
|------|----------|------|
| 简单分类/抽取 | 直接答 / 轻 CoT | 省 token |
| 多步算术、逻辑题 | CoT；不稳再 SC | 中间步骤关键 |
| 答案可投票且容错要求高 | Self-Consistency | 用钱换稳 |
| 必须查库/调 API | ReAct | 没有工具必瞎编 |
| 规划/谜题/多方案比较 | ToT 或 Agent 搜索 | 需要分支与剪枝 |
| 长文案/代码一稿质量差 | Reflection | 低成本二次加工 |
| 延迟敏感（网关在线） | 慎用 SC/ToT | 优先小模型+CoT 或级联 |

**组合拳**（生产常见）：
- `ReAct + Reflection`：工具做完再自检是否答全
- `CoT + 结构化输出`：步骤自由，最终 JSON 硬约束（Day7）
- `级联`：小模型直接答 → 置信低再上 CoT/SC（省平均成本）

## 核心要点

- **CoT**：逼出中间步骤，释放已有推理能力；小模型可能"假推理"。
- **Self-Consistency**：多样本 CoT + 答案投票；代价 ×N；要 temperature>0 才有多样性。
- **ToT**：树搜索 + 中间评估；最贵，留给真规划题；工程上常长成 Agent。
- **ReAct**：Thought ⇄ Action ⇄ Observation；Agent 最小环；Observation 必须来自工具。
- **Reflection**：生成后批评再改；性价比高的质量插件。
- **没有银弹**：先定延迟/成本预算，再选路径；能直接答对就别上重型推理。

## 动手记录

代码：`experiments/reasoning-patterns/reasoning_patterns.py`（纯标准库，不调模型）。

做了什么：
1. 把五种模式都落成 **可解析的 prompt 消息结构** 或 **模拟轨迹**
2. 同一道"订单物流+退款政策"复合题，对比各模式的消息形态、循环步数、代价量级
3. Self-Consistency 用固定 5 条"伪采样轨迹"演示投票（不依赖真 LLM）
4. ReAct 用假工具 `get_logistics` / `get_refund_policy` 跑通 Thought→Action→Observation 环
5. Reflection 演示 draft → critique → revise 三阶段消息

观察到的现象：
- **CoT** 只是 system/user 文案差异，消息条数几乎不变，改造成本最低
- **SC** 结构上是 N 次 CoT；demo 里 5 票中 "可退" 出现 3 次胜出——机制是投票不是更聪明的单次推理
- **ToT** prompt 要描述"扩展/评估/剪枝"协议，上下文明显更重；demo 用 depth=2 × branch=3，剪枝前 13 节点 → beam=2 后 7 节点
- **ReAct** 消息序列最长（多轮 Thought/Action/Observation），但**信息来自工具**，这是前几种纯推理没有的
- **Reflection** 固定 +2 次角色切换，适合做中间件而不是替代工具

## 踩过的坑 / 易混淆点

- **把 CoT 写成散文正确性保证**：步骤错答案仍错；要校验最终字段，必要时校验关键中间量。
- **SC 用 temperature=0**：N 条几乎相同，浪费预算。
- **让模型伪造 Observation**：ReAct 会在幻觉上继续推，错得更圆——Observation 只能工具回填。
- **ToT 和 SC 混为一谈**：SC 是多条独立完整链；ToT 有共享前缀、中间剪枝、可回溯。
- **Reflection 空泛化**："写得更好"没用；要批具体维度（事实、格式、遗漏、安全）。
- **在线网关无脑上 SC/ToT**：P99 延迟炸；应用级联或异步重试路径。

## 面试问答（自测）

- Q: CoT 为什么能提升推理效果？对小模型也有效吗？
  A: 把难题拆成多步，降低单步难度并暴露中间状态。对已有能力的大模型提升明显；过小模型可能生成错误步骤，提升有限甚至有害。
- Q: ReAct 的循环是怎样的？和纯 CoT 的区别？
  A: Thought → Action → Observation 循环直至结束。CoT 只内部推理；ReAct 把工具结果注入上下文，能访问外部世界。
- Q: Self-Consistency 的代价是什么？什么场景值得用？
  A: 约 N 倍延迟/费用。适合离散答案、可投票、正确路径会重复出现的任务；开放生成不适合。
- Q: ToT 和 CoT 差在哪？
  A: CoT 单链；ToT 多分支搜索+中间评估剪枝，可回溯，成本更高，适合规划/谜题。
- Q: Reflection 放在流水线哪一层？
  A: 通常挂在主生成之后、返回用户之前，作可选质量插件；可与 CoT/ReAct 叠加。

## 参考资料

- Wei et al.: Chain-of-Thought Prompting Elicits Reasoning in Large Language Models
- Wang et al.: Self-Consistency Improves Chain of Thought Reasoning in Language Models
- Yao et al.: Tree of Thoughts: Deliberate Problem Solving with Large Language Models
- Yao et al.: ReAct: Synergizing Reasoning and Acting in Language Models
- Shinn et al.: Reflexion: Language Agents with Verbal Reinforcement Learning
- [Anthropic Prompt Engineering](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
