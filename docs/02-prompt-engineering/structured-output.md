# 结构化输出 / Tool Call / 长上下文（Day 7）

> 所属模块：02 · 结构化提示词设计 ｜ 学习日期：2026-07-14

## 一句话总结

线上系统要的不是"漂亮散文"，是**可机器消费的结构**：用 JSON/XML 协议 + schema 约束解码/校验兜底拿稳定字段；用 Tool Calling 把"调外部能力"变成受控的 name+arguments；长上下文则把**关键信息放头尾**，中间塞检索噪声要可丢。

## 我的理解

Day5 解决拼装，Day6 解决推理路径。Day7 解决**出口形态**——下游代码怎么稳稳 `json.loads` / 调工具 / 塞进 100k 上下文还不丢重点。

```
模型自由文本 ──易碎──▶ 下游解析失败 / 幻觉调工具 / 中间信息被淹没

工程化出口：
  ① 结构化输出：schema →（尽量）合法 JSON/XML
  ② Tool Calling：name + arguments 受 schema 约束
  ③ Long Context：头尾放硬约束与问题，中间放可压缩资料
```

### 1. 为什么要结构化输出？

| 自由文本 | 结构化输出 |
|----------|------------|
| "大概是李雷，明天下午吧" | `{"person":"李雷","date":"明天下午","action":null}` |
| 人读舒服 | **程序**读稳定 |
| 难测试、难监控 | 可 schema 校验、可打点字段缺失率 |

**三层稳法**（从软到硬，生产常叠用）：

```
L1 Prompt 约定     "只输出 JSON，不要 Markdown 代码块；缺字段填 null"
L2 API JSON Mode   response_format / 官方 structured output（有则开）
L3 约束解码+校验   解码时屏蔽非法 token；落库前 jsonschema 校验；失败重试/降级
```

只靠 L1 会翻车（模型外包 ` ```json `、尾部加解释、字段改名）。**L1 必做，L2 能开就开，L3 是线上底线。**

### 2. JSON vs XML Prompt

| | JSON | XML 标签 |
|--|------|----------|
| 优点 | 下游生态好、语言原生解析 | 边界清晰、可嵌套长指令/多段资料；Claude 系特别稳 |
| 缺点 | 嵌套引号、尾逗号、代码块污染 | 比 JSON 略啰嗦；部分模型 XML 训练信号弱 |
| 适用 | 最终**业务载荷**、API 响应 | **提示词内部**分区（system 规则、资料、示例） |

实践组合（很常见）：
- **外壳 XML**：`<instructions>` / `<context>` / `<schema>` / `<data>` 分区，防注入、防串味
- **内核 JSON**：模型最终只吐一行/一块 JSON 给解析器

```
system:
  <instructions>只输出 JSON，不要解释</instructions>
  <schema>{"person":"string|null", ...}</schema>
user:
  <data>{用户原文}</data>
```

> 面试常问"为什么 XML 对长指令更稳"：标签显式闭合，模型更易把"指令块"和"数据块"当不同注意力区域；长文档塞进 `<doc id=1>` 比纯换行更不容易和问题粘连。

### 3. 合法 JSON 的失败模式与兜底

常见脏输出：
1. Markdown 代码块：` ```json ... ``` `
2. 前后废话：`好的，结果如下：{...} 希望有帮助`
3. 尾逗号 / 单引号 / `True/None`（Python 风）
4. 截断：`max_tokens` 砍在半个对象中间
5. schema 漂移：多字段、少字段、类型错

**兜底流水线**（实验里会跑通）：

```
raw
  → strip 代码块围栏
  → 截取第一个 { 到最后一个 }（或 [ ]）
  → json.loads
  → 失败则：修复常见问题 / 二次 prompt「只修 JSON」/ 返回默认 + 告警
  → jsonschema 或手写字段检查
  → 仍失败 → 业务降级（人工队列 / 上一版缓存 / 安全默认值）
```

原则：**解析失败是预期事件**，不是异常惊喜。监控 `parse_ok_rate`、`schema_ok_rate`。

### 4. Tool Calling / Function Calling Prompt

和 Day6 ReAct 文本协议是**同一语义、两种载体**：

| | 文本 ReAct | 原生 Tool Calling |
|--|------------|-------------------|
| 形态 | `Action: foo\nAction Input: {...}` | API 字段 `tool_calls[{name, arguments}]` |
| 解析 | 自己写正则 | 运行时/SDK 解析 |
| 约束 | 靠 prompt | 常有 JSON Schema 约束 arguments |
| 适用 | 教学、无原生 FC 的模型 | 生产默认 |

**Prompt / 工具定义要点**：
1. **一个工具一件事**；name 稳定、动词清晰（`get_logistics` 而非 `do_stuff`）
2. **parameters 用 JSON Schema**：类型、required、enum、description 写进人话
3. description 写**何时调用 / 不何时调用**，减少乱调
4. 返回给模型的 tool result 要**短而结构化**，别把 10 页 HTML 塞回去
5. 敏感工具（转账、删库）→ 后端鉴权，**不信模型一句 arguments**

```
tools = [{
  "name": "get_logistics",
  "description": "查询订单物流。仅当用户问物流/签收且提供或上下文有 order_id 时调用。",
  "parameters": {
    "type": "object",
    "properties": {
      "order_id": {"type": "string", "description": "订单号，如 8821"}
    },
    "required": ["order_id"]
  }
}]
```

**失败兜底**：arguments 解析失败 → 重问缺参；未知 tool name → 拒绝执行并提示模型；超时/工具 5xx → Observation 写错误，让模型改口或 finish 道歉，而不是空转。

### 5. 约束解码（概念，Gateway/Serving 会再遇）

普通采样：每步从全词表按概率抽 token。  
**约束解码**：根据当前已生成前缀 + schema，把**不可能合法的 token 概率置 0** 再采样。

```
要生成 JSON 且下一个该是 key 或 } 时：
  允许: "  }  ,
  禁止: 随便一个中文词、解释性前缀
```

效果：语法层合法性大幅上升；**语义**对不对仍靠模型与校验（合法 JSON 也可以是错字段值）。  
和 JSON Mode 关系：很多厂商的 JSON Mode = 约束解码的产品化开关。

### 6. Long Context 信息组织

窗口到了 100k/200k，不等于"把百科全书塞进去模型全能记住"。

**Lost in the Middle**（经典结论）：模型对上下文**开头和结尾**更敏感，**中间**的事实更容易被忽略。

```
[系统硬约束 / 角色 / 输出 schema]   ← 头：稳定、短、硬
[检索到的 doc1 … docK 按相关度]      ← 中：可压缩、可丢
[当前用户问题 / 最新工具结果]        ← 尾：任务焦点（recency）
```

工程抓手：
1. **头**：身份、安全、输出格式（短）
2. **中**：RAG 文档，相关度排序，超预算就截断/摘要/重排后再塞
3. **尾**：用户问题、对话最新轮、必须引用的关键字段
4. **重复锚定**：极硬约束可在尾部再写一行（双写），抗中间噪声
5. **引用标记**：`[doc_3]` 要求答案带引用 → 可审计，也逼模型回看对应段

和 Gateway 的关系：长上下文 = 更高 prefill 成本与 TTFT；能检索就别全量塞，**先小后大**（模块 03 RAG）。

### 7. 和前两天的拼装关系

```
Day5 模板/角色  ──拼出──▶ messages
Day6 推理路径   ──可选──▶ CoT / ReAct 包一层
Day7 出口控制   ──约束──▶ JSON schema / tool_calls / 头尾布局
         │
         ▼
   解析校验 → 业务系统 / 再进 Agent 环
```

## 核心要点

- **结构化输出是契约**：prompt 约定 + JSON Mode + 校验/重试，三层叠用。
- **XML 适合分区指令与资料，JSON 适合业务载荷**；可组合。
- **脏 JSON 是常态**：strip 围栏、抽括号、schema 校验、失败降级要写进链路。
- **Tool Calling = 受 schema 约束的 ReAct**；敏感副作用必须后端鉴权。
- **约束解码保语法，不保语义正确。**
- **长上下文：重要信息放头尾**；中间放可丢资料；硬约束可双写。

## 动手记录

代码：`experiments/structured-output/structured_output_demo.py`（纯标准库）。

1. **脏 JSON 清洗**：代码块围栏、前后废话、尾逗号 → 解析成功；再跑 schema 字段检查  
2. **失败兜底**：不可修复样本 → `parse_ok=False`，返回安全默认并记原因  
3. **XML 分区抽取**：从 `<data>` 取用户原文，指令区与数据区分离  
4. **Tool schema 校验**：合法 `order_id` 通过；缺 required / 类型错 / 未知工具名拒绝  
5. **长上下文位置效应（模拟）**：同一关键事实放在头/中/尾，用"可检索性启发式"展示中间最易丢——对应 Lost in the Middle 的工程直觉（非真模型注意力实验）

## 踩过的坑 / 易混淆点

- **JSON Mode ≠ 字段正确**：语法过了，`person` 仍可能张冠李戴 → 要业务校验/抽检。
- **禁止代码块只写在 prompt 不够**：解析层必须 strip，双保险。
- **Tool 描述写太虚**：模型乱调或从不调；写清触发条件与反例。
- **把长 HTML 当 tool result**：上下文爆炸且中间噪声；先摘要/抽字段。
- **长上下文只塞不治理**：成本涨、命中率未必涨；先 rerank 再进窗。
- **ReAct 文本协议 vs 原生 FC 二选一宗教战**：语义相同；有原生 FC 用原生，解析更稳。

## 面试问答（自测）

- Q: 怎么让模型稳定输出合法 JSON？失败了怎么兜底？
  A: Prompt 约定 schema + 禁代码块；能开 JSON Mode/约束解码就开；解析层 strip/截取/重试；schema 校验失败则二次修复调用或业务降级，并监控成功率。
- Q: 长上下文里信息放哪最有效？为什么？
  A: 头尾更有效（U 形注意力/Lost in the Middle）。头放规则与 schema，尾放当前问题与最新证据，中间放可压缩检索结果。
- Q: Tool Calling 和纯 CoT 差在？
  A: CoT 只内部推理；Tool Calling/ReAct 产生受 schema 约束的外部动作，结果再进上下文。
- Q: XML 和 JSON 在提示词里怎么分工？
  A: XML 做分区与长指令边界；JSON 做最终机器可读载荷。
- Q: 约束解码能解决幻觉吗？
  A: 不能完全。它主要保证语法/schema 形态合法；事实幻觉要靠检索、工具真值与校验。

## 参考资料

- [OpenAI: Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- [Anthropic: Use XML tags](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/use-xml-tags)
- [Anthropic: Long context prompting tips](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips)
- Liu et al.: Lost in the Middle: How Language Models Use Long Contexts
- OpenAI Function Calling / Tool Calling 文档
