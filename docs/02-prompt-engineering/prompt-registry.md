# Prompt 工程化：Registry / 版本 / 测试（Day 8）

> 所属模块：02 · 结构化提示词设计 ｜ 学习日期：2026-07-14

## 一句话总结

企业里的 Prompt 不是聊天框里的一段话，而是**带 ID、版本、测试与流量的软件构件**：Registry 管注册与解析，版本可钉扎/可回滚，golden + 评估门禁防回归，A/B 用数据而不是体感发版。

## 我的理解

Day5~7 解决了"怎么写好一条 prompt"。Day8 解决"**一百条 prompt 上了线怎么活**"——改坏谁负责、回滚怎么做、A/B 怎么切、CI 怎么拦。

```
仓库 prompts/                 运行时
┌──────────────┐            ┌─────────────────────┐
│ id@version   │  register  │ PromptRegistry      │
│ system/user  │ ─────────▶ │  get(id, version?)  │
│ few-shot     │            │  resolve(alias)     │
│ tests/golden │            │  ab_route(user_key) │
└──────────────┘            └──────────┬──────────┘
                                       │ build(vars)
                                       ▼
                                messages + meta
                                (template_id, version, experiment)
```

### 1. 为什么要 Registry？

没有 Registry 时：
- 字符串散落在业务代码 / 配置中心 / 某人笔记
- 改一处漏一处；出事故不知道线上跑的是哪一版
- 无法 A/B：流量和文案绑死在分支里

有 Registry 时：
- **唯一入口**：`registry.get("classify-intent", version="v2")`
- **元数据齐全**：id / version / owner / 变量列表 / 创建时间
- **策略可插**：默认 latest、钉扎生产版本、按用户哈希 A/B

类比：容器镜像仓库。镜像 = 模板内容；tag = version；latest 慎用在生产。

### 2. 版本管理模型

| 策略 | 含义 | 适用 |
|------|------|------|
| **语义版本 / 单调 vN** | `v1` `v2` 不可变内容 | 教学与多数业务足够 |
| **内容哈希** | `sha256[:8]` 变了才新版本 | 强审计、防偷改 |
| **别名 alias** | `prod` → `classify-intent@v2` | 发布与回滚只改指针 |
| **钉扎 pin** | 请求强制 `version=v1` | 关键链路、合规复现 |

**不可变原则**：已发布的 `id@version` **禁止改内容**。要改就发 `v3`，`prod` 指针再切。改历史版本 = 毁掉复现与审计。

```
发布流：
  dev 改草稿 → 跑 golden 测试 → 注册 vN（不可变）
  → 小流量 alias canary → 指标 OK → alias prod 指向 vN
  → 指标炸 → prod 指回 vN-1（秒级回滚，不用改代码）
```

### 3. 测试钩子：把 prompt 当纯函数测

Prompt 渲染是**纯函数**：`(template, variables) → messages`。  
不调模型也能测一大截：

| 测试类型 | 测什么 | 是否需要 LLM |
|----------|--------|--------------|
| **渲染/快照** | 变量注入、角色顺序、few-shot 条数 | 否 |
| **契约** | 必含 schema 关键字、`<data>` 包裹、禁出现密钥 | 否 |
| **Golden** | 固定 vars 下 messages 与快照一致 | 否 |
| **解析契约** | 假模型输出能被 Day7 清洗+schema 过 | 否（用夹具） |
| **效果评估** | 真模型准确率 / LLM-as-Judge | 是（模块 05 加深） |

**Golden 测试防回归**：改了模板空格或 few-shot 顺序，CI 红——逼你承认"行为变了"，而不是静默漂移。

评估（有模型时）最小闭环：
1. 固定评测集（输入 + 期望标签/关键字段）
2. 跑候选版本
3. 算准确率 / schema_ok_rate / 延迟 / 成本
4. **门禁**：不低于 prod 或不超过预算才允许切 alias

### 4. A/B 与实验

```
user_key ──hash──▶ 桶 0~99
                      │
          ┌───────────┼───────────┐
       0~89          90~94       95~99
       prod           v3          v4
```

要点：
- **同一 user 稳定落桶**（哈希 user_id，不是随机每次变）
- 日志打上 `template_id` + `version` + `experiment_id`，否则无法归因
- 先比 **可机读指标**（解析成功率、工具非法率），再比业务指标
- 样本不够别急着全量；小流量看 P95 延迟与报错

### 5. Prompt SDK / DSL 最小设计

生产 SDK 不必上大框架，四个能力够用：

1. **Template**：变量渲染、缺变量早失败（Day5 已有）
2. **Builder**：system / few-shot / user 拼 messages（Day5）
3. **Registry**：注册、按 id/version/alias 解析、列表、元数据
4. **Hooks**：`before_build` / `after_build` / `assert_messages`（测试与观测）

可选增强（模块 06 Gateway 会再遇）：
- 远程配置下发 alias
- 与 Tracing 打通（每个请求带 prompt 版本）
- 多环境：`dev` / `staging` / `prod` 三套 alias 表

```
# 伪代码
reg = PromptRegistry()
reg.register(spec)                 # id=classify-intent, version=v2
reg.set_alias("prod", "classify-intent", "v2")
spec = reg.resolve("classify-intent", alias="prod")
messages = spec.build(query="...")
assert_hooks(messages)             # CI 同款
```

### 6. 和前三天的拼装关系（模块 02 全图）

```
Day5  Template + 角色 + Few-shot     →  单条能写对
Day6  CoT / SC / ToT / ReAct / Reflect →  路径能选对
Day7  JSON / Tool / Long Context      →  出口能解析
Day8  Registry / 版本 / 测试 / A/B    →  上线能管住
```

面试一句话：**Prompt Platform = Git 式版本 + 配置中心式路由 + 单测式门禁 + 可观测元数据。**

## 核心要点

- **id@version 不可变**；发布与回滚靠 alias 指针，不靠改历史。
- **Registry 是唯一解析入口**，禁止业务里硬编码长 prompt 字符串。
- **无模型也能测**：渲染快照、契约、golden；有模型再上效果评估。
- **A/B 要稳定分桶 + 全链路打点 version**。
- **SDK 最小四件套**：Template / Builder / Registry / Hooks。
- **观测字段**：`template_id` `version` `alias` `experiment_id` 进日志与 trace。

## 动手记录

代码：`experiments/prompt-sdk/prompt_registry.py`（纯标准库）。

1. **Registry 注册** `classify-intent@v1` / `@v2`（v2 多一条 other 示例）  
2. **alias**：`prod → v1`，发布后切 `prod → v2`，回滚再指回 v1  
3. **钉扎**：`get(id, version="v1")` 不受 alias 影响  
4. **A/B**：`ab_route(user_key, weights)` 同 key 稳定；不同 key 可分到 v1/v2  
5. **Golden 钩子**：固定 vars 渲染后做契约断言（含 system 标签、data 包裹、消息角色序列）  
6. **变更检测**：v2 与 v1 的 few-shot 数不同 → golden 差异显式暴露  

## 踩过的坑 / 易混淆点

- **latest 当生产**：有人推了坏版本全站遭殃；生产用 alias 显式切换。
- **改了 v1 文件还叫 v1**：毁掉审计；内容变必须新版本号。
- **只 A/B 不打点**：事后无法知道用户吃到哪版。
- **用真模型做唯一测试**：慢、贵、抖；先黄金/契约，再抽检效果。
- **Registry 里塞业务逻辑**：Registry 只管解析与元数据；编排仍在调用方。
- **版本号当功能开关滥用**：开关用配置；版本表达的是 prompt 内容快照。

## 面试问答（自测）

- Q: 企业里 Prompt 怎么做版本管理和评估？
  A: id@version 不可变入库；alias（prod/canary）做发布与回滚；CI 跑渲染/golden/契约；上线前用固定集评准确率与 schema_ok_rate；日志带 version 做归因与 A/B。
- Q: 不调 LLM 能测 prompt 吗？
  A: 能。测变量渲染、消息结构、安全契约、与假输出解析链路；效果类指标才需要模型或 LLM-as-Judge。
- Q: A/B 要注意什么？
  A: 用户稳定分桶、流量与版本可观测、先看工程指标再看业务、可一键回滚 alias。
- Q: Prompt Registry 和配置中心什么关系？
  A: Registry 是领域模型（模板语义+版本）；配置中心可存 alias 指针与开关，但内容仍建议进 Git 做 code review。
- Q: 和 Day5 Builder 怎么分工？
  A: Builder 负责单次拼装；Registry 负责多模板的注册、解析、实验路由；Hooks 负责测试与观测。

## 参考资料

- 模块内：`prompt-template-basics.md` / `structured-output.md`
- OpenAI / Anthropic Prompt 工程指南（迭代与评测章节）
- 软件工程类比：语义化版本、功能开关、金丝雀发布
- 模块 05：LLM-as-Judge 与更系统的评测集设计
