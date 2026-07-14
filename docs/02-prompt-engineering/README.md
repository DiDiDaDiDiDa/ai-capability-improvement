# 模块 02 · 结构化提示词设计框架

> 预计 15h ｜ 对应学习方案第二阶段

## 学习目标

跳过"你是一位专家…请一步步思考"这类过时写法，学工程化的提示词体系：模板化、结构化输出、工具调用、版本与评估。目标是**自己写出一个 Prompt SDK**，理解企业里的 Prompt Platform 是怎么回事。

## 知识地图

```
Prompt Template（变量注入 / 分层 system-user-assistant）
        │
   ┌────┴─────────────────────────────┐
   │                                   │
推理增强                          输出控制
CoT / Self-Consistency            JSON / XML 结构化输出
Tree-of-Thought                   Tool Calling Prompt
ReAct / Reflection                Long Context 组织
   │                                   │
   └──────────────┬────────────────────┘
                  │
        工程化：模板库 / 版本 / 测试 / 评估（Prompt Registry）
```

## 核心概念清单

### 1. 模板与基础
- Prompt Template、变量注入、复用
- System / User / Assistant 角色分层
- Few-shot：示例选择、顺序、数量的影响
- Zero-shot vs Few-shot 的取舍

### 2. 推理增强技术
- Chain-of-Thought（CoT）：让模型显式推理
- Self-Consistency：多次采样投票
- Tree-of-Thought（ToT）：搜索式推理
- ReAct：Reasoning + Acting 交替
- Reflection：自我批评与修正

### 3. 输出控制
- 结构化输出：JSON Mode、XML Prompt，为什么 XML 对长指令更稳
- Tool Calling / Function Calling 的 prompt 设计
- 约束解码、schema 校验思路
- Long Context 的信息组织（重要信息放头尾）

### 4. 提示词工程化
- Prompt 版本管理、A/B 测试
- Prompt 评估（结合模块 05 的 LLM-as-Judge）
- Prompt Registry / DSL / Builder 的设计

## 建议产出物

- [x] 最小 Prompt Builder（Python）：模板渲染、变量注入、few-shot 拼装、版本标记（`experiments/prompt-builder/prompt_builder.py`，Day5）
- [x] 常用提示词模板沉淀到仓库 `prompts/`（`classify-intent.v1.md` / `extract-json.v1.md`，Day5 起步）
- [ ] 一组 CoT / ReAct / 结构化输出的对比样例（`experiments/`，Day6~7）
- [ ] Prompt SDK 完整版：版本管理 / 测试钩子（Day8）

## 面试高频题（出口自测）

1. CoT 为什么能提升推理效果？对小模型也有效吗？
2. ReAct 的循环是怎样的？和纯 CoT 的区别？
3. 怎么让模型稳定输出合法 JSON？失败了怎么兜底？
4. Few-shot 示例的数量和顺序会影响结果吗？
5. Self-Consistency 的代价是什么？什么场景值得用？
6. 长上下文里信息放哪最有效？为什么？
7. 企业里 Prompt 怎么做版本管理和评估？

## 资源

- OpenAI / Anthropic 官方 Prompt Engineering 指南
- ReAct / Tree-of-Thoughts / Self-Consistency 原论文
- Anthropic: Prompt engineering（XML、long context 部分）

## 检查清单

- [ ] 能区分并落地 CoT / ToT / ReAct / Reflection
- [ ] 能设计稳定的结构化输出与工具调用 prompt
- [ ] 写出了可复用的 Prompt SDK
- [ ] 能回答上面全部面试题
