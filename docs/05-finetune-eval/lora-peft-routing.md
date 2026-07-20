# LoRA / PEFT / 选型：改权重还是改上下文

> 所属模块：05 · 微调与评估 ｜ 学习日期：2026-07-20  
> 实验：`experiments/finetune-eval/finetune_eval_demo.py`（LoRA 参数量/前向、QLoRA 存储、SFT/DPO 定位、选型决策全绿）

## 一句话总结

**Prompt 改行为，RAG 补知识，FineTune 固化风格/格式**；LoRA 用低秩旁路只训小矩阵，QLoRA 再把基座权重量化省显存——Infra 岗要会选型与账本，不必会炼 70B。

## 我的理解

```
能力增强三板斧（成本从低到高）

  Prompt ──▶ 改指令/格式/少样本        即时、可回滚
  RAG    ──▶ 检索外挂知识 + 引用        知识可更新、可溯源
  FineTune─▶ 改模型条件分布（权重/适配器）  风格稳、更新贵

PEFT / LoRA 把「全量改 W」变成「冻 W + 训 ΔW≈BA」
```

### LoRA 为什么高效

全量线性层 \(y = xW\)，\(W\in\mathbb{R}^{d\times d}\) 参数 \(d^2\)。  
LoRA 设 \(\Delta W = AB\)（实现上 \(A\in\mathbb{R}^{d\times r}, B\in\mathbb{R}^{r\times d}\)），**只训** \(A,B\)：

\[
y = xW + \frac{\alpha}{r}\, xAB
\]

- \(W\) **冻结**（可量化存储）  
- 可训参数 \(2dr\)；\(d=512,r=8\) → **8192 / 262144 ≈ 3.125%**  
- 常见初始化：\(B=0\) → 起步 \(\Delta W=0\)，不破坏基座  
- 秩 \(r\) 是适配容量旋钮：太小欠拟合，太大接近全量成本  

实验断言：`B=0` 时 \(y=xW\)；改 \(B\) 后输出必动；`scale=α/r`。

### QLoRA 多做了什么

| | LoRA | QLoRA |
|--|------|-------|
| 基座 W | 通常 FP16/BF16 驻留 | **4bit/8bit 量化存放**，算时反量化 |
| 适配器 | FP16 训 A/B | 同左 |
| 目的 | 少训参数 | **少显存** 仍能微调大模型 |

教学账（\(64\times64\) INT8）：FP16 full 8192B → INT8 base+LoRA **5120B**。  
面试点：**QLoRA = 量化压缩基座 + LoRA 适配**，不是「把 LoRA 也量化掉就不训了」。

### SFT / DPO / RLHF（流程定位）

```
SFT:   (x, y*) 单条模仿        → 会做题、会格式
RLHF:  偏好 → 奖励模型 RM → RL  → 重、不稳、工程复杂
DPO:   (x, y_w, y_l) 直接偏好对 → 省 RM+RL，对齐更轻
```

- **SFT** 学「标准答案长什么样」  
- **DPO/RLHF** 学「两个答案里哪个更好」——解决的是偏好，不是往权重里塞百科  

实验：SFT proxy loss good≪bad；DPO score 在 chosen logp 更高时 >0.5。

## 选型决策表（面试抓手）

| 信号 | 优先 |
|------|------|
| 只要改语气/格式/JSON 壳 | **Prompt** |
| 外部知识、要引用、周更 | **RAG** |
| 固定话术/领域格式、知识不卷进权重 | **FineTune**（LoRA） |
| 高量客服：知识变 + 口吻稳 | **RAG + FineTune** |
| 把「本周制度」烤进权重 | **不该 FT** → 过期即事故 |

规则引擎见实验 `choose_stack()`——能讲清 if-else 比背口号强。

## 动手记录

```bash
cd experiments/finetune-eval && python3 finetune_eval_demo.py
# LoRA ratio=3.12% | QLoRA store 5120<8192 | DPO=0.56 | EXIT:0
```

## 踩过的坑 / 易混淆点

- **FT 当知识库**：制度周更却全量/LoRA 硬背 → 应用层该 RAG。  
- **LoRA 训全参数**：忘了冻 W，PEFT 名存实亡。  
- **QLoRA = 只量化不适配**：量化是存基座，能力迁移仍靠 A/B。  
- **DPO 替代 SFT**：通常先 SFT 再偏好对齐，不是二选一互斥。

## 面试问答（自测）

- **Q: 何时 FT / RAG / Prompt？** 见上表。  
- **Q: LoRA 训什么？** 低秩 \(A,B\)，\(W\) 冻结；参数约 \(2dr\)。  
- **Q: QLoRA 比 LoRA 多啥？** 基座量化省显存。  
- **Q: SFT vs DPO？** 单条模仿 vs 成对偏好；DPO 省 RM+RL。

## 参考资料

- LoRA / QLoRA 论文；Hugging Face PEFT  
- 实验：`experiments/finetune-eval/finetune_eval_demo.py`
