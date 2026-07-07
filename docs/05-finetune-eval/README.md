# 模块 05 · 模型微调与量化评估

> 预计 10h ｜ 对应学习方案第五阶段

## 学习目标

AI Infra 岗位不用深入训练细节，但要能答清楚选型决策：**什么时候用 Prompt、什么时候用 RAG、什么时候才微调**。同时掌握主流评估方法。

## 知识地图

```
能力增强手段的选型
  Prompt  ──▶ 最轻，改行为/格式
  RAG     ──▶ 补知识、可溯源、易更新
  FineTune──▶ 改风格/固化能力，成本高、更新难
        │
   微调方法：SFT → LoRA / QLoRA → DPO / RLHF
        │
   量化：INT8 / INT4，显存与精度权衡
        │
   评估：BLEU / ROUGE / BERTScore / LLM-Judge / Arena
```

## 核心概念清单

### 1. 微调方法
- 全量微调 vs PEFT（参数高效微调）
- LoRA：低秩适配的原理（为什么只训练小矩阵）
- QLoRA：量化 + LoRA，如何在小显存上微调
- SFT（监督微调）、DPO、RLHF 的定位与流程概念

### 2. 量化
- INT8 / INT4 量化，GPTQ / AWQ 概念
- 量化对显存、吞吐、精度的影响

### 3. 选型决策（面试重点）
- Prompt vs RAG vs FineTune 的判断标准
- 什么时候"不该"微调
- 知识更新频繁 → RAG；风格/格式固化 → 微调；简单行为调整 → Prompt

### 4. 评估
- 传统指标：BLEU、ROUGE、BERTScore（各自衡量什么）
- LLM-as-Judge：优点与偏差（位置偏差、长度偏差）
- Arena / 人类偏好评测
- Prompt Evaluation：怎么系统化评估一个 prompt 的好坏

## 建议产出物

- [ ] 一次最小 LoRA / QLoRA 微调实验（小数据集，跑通即可，记录到 `experiments/`）
- [ ] 一套评测脚本：给定输出算 ROUGE + 跑一个 LLM-Judge
- [ ] 一页"Prompt / RAG / FineTune 选型决策表"

## 面试高频题（出口自测）

1. 什么时候用微调，什么时候用 RAG，什么时候只需要 Prompt？
2. LoRA 为什么高效？训练的是什么？
3. QLoRA 相比 LoRA 多做了什么？
4. SFT 和 DPO / RLHF 的区别？
5. BLEU / ROUGE 分别衡量什么？局限是什么？
6. LLM-as-Judge 有哪些已知偏差？怎么缓解？
7. INT4 量化会带来什么代价？

## 资源

- LoRA / QLoRA 原论文
- Hugging Face PEFT 文档
- DPO 论文
- 各评估指标（BLEU/ROUGE/BERTScore）原始资料

## 检查清单

- [ ] 能清晰讲出 Prompt/RAG/FineTune 选型逻辑
- [ ] 理解 LoRA/QLoRA 原理并跑过一次实验
- [ ] 能设计一套基础评测流程
- [ ] 能回答上面全部面试题
