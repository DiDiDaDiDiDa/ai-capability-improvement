# Prompts · 提示词沉淀

沉淀可复用的提示词模板、版本演进和使用场景说明。对应模块 02 的工程化实践。

## 组织方式

- 文件名：`<template_id>.<version>.md`（例：`extract-json.v2.md`）
- **已发布版本内容视为不可变**；要改行为就加新版本文件
- 运行时通过 Prompt Registry 的 `id@version` / alias 解析（见 `experiments/prompt-sdk/`）

## 清单

| 文件 | template_id | 版本 | 用途 |
|------|-------------|------|------|
| `classify-intent.v1.md` | classify-intent | v1 | 电商意图分类 + few-shot |
| `extract-json.v1.md` | extract-json | v1 | JSON 抽取起步 |
| `extract-json.v2.md` | extract-json | v2 | XML 分区 + null 示例 |
| `cot-solve.v1.md` | cot-solve | v1 | Zero-shot CoT |
| `react-agent.v1.md` | react-agent | v1 | 文本 ReAct 工具环 |
| `tool-call-logistics.v1.md` | tool-call-logistics | v1 | 原生 Tool Calling schema |

## 单条模板建议格式

```
# <提示词名称>
用途：
变量：{var1} {var2}
版本：vN（YYYY-MM-DD）
适用模型：
template_id：
---
<提示词正文>
---
效果记录 / 迭代说明：
```

## 发布检查（Day8）

1. 新版本号，不覆盖旧文件语义  
2. 本地跑 Registry golden / 契约钩子  
3. alias `canary` → 观察 → `prod`  
4. 日志确认 `template_id` + `version` 已打点  
