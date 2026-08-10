# DPO / RLHF 流程与 INT8·INT4 量化账

> 所属模块：05 · 微调与评估 ｜ 学习日期：2026-08-10  
> 实验：`experiments/finetune-eval/finetune_eval_demo.py`（§2 QLoRA 存储账 + §3 SFT→DPO/RLHF 定位）  
> 选型总览仍见：[`lora-peft-routing.md`](lora-peft-routing.md)

## 一句话总结

**SFT 教「标准答案长什么样」，DPO/RLHF 教「两个答案里哪个更好」**；量化（INT8/INT4）是 **Serving/训练显存账**，和「偏好对齐」正交——QLoRA 只是把两者叠在同一条微调链路上。

## 我的理解

### 1. 对齐流水线：SFT →（RLHF | DPO）

```
语料
  │
  ▼
┌──────── SFT ────────┐
│ 数据: (x, y*)       │  模仿单条 gold
│ 损失: CE / NLL      │  会格式、会任务壳
└──────────┬──────────┘
           │  策略 π_SFT
           ▼
    ┌──────┴──────┐
    │             │
    ▼             ▼
┌─ RLHF ──┐  ┌── DPO ──────────────┐
│ 1 偏好标注│  │ 数据: (x, y_w, y_l) │
│ 2 训 RM  │  │ 直接拉高 chosen、   │
│ 3 RL 优化│  │ 压低 rejected      │
│   π vs RM│  │ 相对 ref 策略约束   │
└────┬─────┘  └──────────┬─────────┘
     │                   │
     └─────────┬─────────┘
               ▼
          对齐后策略 π*
```

| | SFT | RLHF | DPO |
|--|-----|------|-----|
| 监督信号 | 单条 y\* | 标量奖励 r(x,y) | 成对 y_w ≻ y_l |
| 额外模型 | 无 | **Reward Model** | 通常要 **ref**（冻结 SFT） |
| 优化 | 监督学习 | RL（PPO 等） | 分类式闭式目标 |
| 工程体感 | 稳、成熟 | 重、超参敏感、不稳 | 相对轻，仍吃偏好数据质量 |
| 解决的问题 | 会做 | **更符合人类偏好** | 同左，路径更短 |

**不是互斥**：工业默认 **先 SFT 再偏好对齐**。DPO 替代的是「RM+RL 这段」，不是替代 SFT。

### 2. DPO 在优化什么（面试可写的形）

直觉：希望模型在 prompt \(x\) 上对 **chosen** 的对数概率高于 **rejected**，且不要离参考策略 \(\pi_{\mathrm{ref}}\) 太远。

教学版（实验 `dpo_pref_score`，故意去掉 ref，只演示成对信号）：

\[
s = \sigma\bigl(\beta\,(\log\pi(y_w\mid x)-\log\pi(y_l\mid x))\bigr)
\]

- \(s>0.5\)：当前策略已经更偏好 chosen  
- 实验断言：`chosen_logp=-1.2, rejected=-3.5` → score≈0.56；对调 logp → score\<0.5  

完整 DPO 还会减 \(\log\pi_{\mathrm{ref}}\) 项（KL 锚），防止模型为抬 margin 而极端化。Infra 岗记住三句话即可：

1. **数据形态是偏好对，不是单条标准答案**  
2. **目标是相对排序，不是模仿某一个 y\***  
3. **β / ref 是稳定性旋钮**，不是装饰

### 3. RLHF 为什么重

```
人类/AI 标注 y_a ≻ y_b
        ▼
   训练 Reward Model  rθ(x,y)
        ▼
   用 PPO 等更新 π，使 E[r]↑ 且 KL(π||π_ref) 有界
```

痛点：

- **三套模型**（策略、ref、RM）+ 采样闭环  
- 奖励 hacking：π 钻 RM 空子  
- 延迟与算力：对齐阶段常比 SFT 更贵  

所以 DPO 爆火的底层逻辑是：**同一偏好数据，去掉 RM+RL 的工程面**。

### 4. 量化：INT8 / INT4 在算什么账

量化 = 用更少 bit 存（有时也算）权重/激活，换 **显存与带宽**，付 **精度**。

| | FP16 基座 | INT8 | INT4 |
|--|-----------|------|------|
| 每参数 | 2 B | 1 B | 0.5 B |
| 70B 量级粗算 | ~140 GB | ~70 GB | ~35 GB |
| 典型用途 | 训练/高精度推理 | 推理省显存；QLoRA 存基座 | 端侧/高密度推理；QLoRA 更狠 |
| 主要代价 | — | 校准/误差 | 掉点风险↑，对校准与核实现更敏感 |

**GPTQ / AWQ（概念级）**：

- 都是 **权重量化** 流派，推理期省显存  
- 差在校准与误差分配（层/通道敏感度、激活感知等）  
- Infra 选型看：内核成熟度、模型族支持、吞吐 vs 质量曲线，而不是背公式

**和 QLoRA 的咬合**（实验 §2 已断言）：

```
QLoRA = 量化压缩【冻结基座 W】+ 仍用 FP16/BF16 训【小矩阵 A,B】
```

教学账（\(64\times64\)）：FP16 full 8192B → INT8 base + LoRA **5120B**，且 toy INT8 RMSE\<0.05。  
**不是**「把 LoRA 也量化掉就不训了」。

### 5. Serving 量化 vs 训练量化

| | 训练侧（QLoRA） | Serving 侧（GPTQ/AWQ/FP8…） |
|--|-----------------|------------------------------|
| 目标 | 小显存上**还能微调** | 小显存/高吞吐上**提供推理** |
| 可训部分 | A,B 通常高精度 | 一般整模冻结 |
| 与对齐关系 | 可对 QLoRA 再 DPO | 对齐完成后的部署压缩 |

面试点：**INT4 的代价**不只是「数字变粗」，还有：个别任务掉点、长尾 token 不稳、与 flash-attn/内核版本绑定——要 **任务集回归**，不能只看 MMLU 平均分。

## 动手记录

```bash
cd experiments/finetune-eval && python3 finetune_eval_demo.py
# §2 QLoRA: INT8 base+LoRA 存储 < FP16 full；forward OK
# §3 SFT proxy: good loss < bad；DPO score 正序 >0.5> 反序
# EXIT:0
```

关键符号：

- `quantize_int8_symmetric` / `dequant_int8` / `demo_qlora`  
- `sft_loss_proxy` / `dpo_pref_score` / `demo_alignment_pipeline`  
- 选型仍走 `choose_stack`（知识周更 → RAG，不靠 FT 烤进权重）

## 踩过的坑 / 易混淆点

- **DPO 替代 SFT**：数据与目标都不同；顺序是 SFT → DPO。  
- **有偏好数据就上 RLHF**：多数团队 DPO/同类离线目标更省事；RLHF 留给要在线探索或复杂奖励的场景。  
- **量化 = 一定掉点到不能用**：看 bit 数、校准、任务；INT8 常可接受，INT4 要单测业务集。  
- **QLoRA 的 4bit 是在训适配器**：基座低 bit 存，适配器仍高精度训。  
- **对齐解决知识过期**：偏好对齐不写新事实；制度周更仍是 RAG 的活。

## 面试问答（自测）

- **Q: SFT 和 DPO/RLHF 的区别？**  
  A: SFT 模仿单条 (x,y\*)；DPO/RLHF 用偏好让 π 更偏 y_w 而非 y_l。RLHF 经 RM+RL；DPO 直接成对目标，省 RM+RL。

- **Q: 为什么常先 SFT 再 DPO？**  
  A: 先有可用来做题的策略与格式，再在偏好方向上排序；从随机策略直接偏好对齐样本效率差。

- **Q: INT4 量化代价？**  
  A: 显存/带宽换精度；可能任务掉点、实现与硬件绑定；需业务回归。Serving 量化 ≠ 自动获得 QLoRA 训练能力。

- **Q: QLoRA 和 INT4 Serving 是一回事吗？**  
  A: 否。QLoRA 是训练期「冻基座量化 + 训 LoRA」；Serving INT4 是部署压缩。可先后发生在同一模型生命周期。

- **Q: 偏好数据脏了会怎样？**  
  A: DPO/RLHF 都会学坏偏好（谄媚、奖励 hacking）。对齐质量上限 ≈ 标注/AI 偏好数据质量上限。

## 参考资料

- DPO 论文；InstructGPT / RLHF 综述  
- LoRA / QLoRA 论文；GPTQ / AWQ 概念文  
- 实验：`experiments/finetune-eval/finetune_eval_demo.py`  
- 同模块：[`lora-peft-routing.md`](lora-peft-routing.md)、[`eval-metrics-judge.md`](eval-metrics-judge.md)
