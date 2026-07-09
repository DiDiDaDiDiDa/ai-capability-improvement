# Transformer 架构（Day 3）

> 所属模块：01 · NLP 与深度学习基础 ｜ 学习日期：2026-07-08

## 一句话总结

Transformer 靠 Self-Attention 让每个词根据上下文动态更新表示；再叠加 Multi-Head、残差+LayerNorm、FFN、位置编码，堆 N 层构成大模型骨架。Decoder-only + KV Cache 是当下主流生成模型的核心。

## 我的理解：Self-Attention（核心）

让序列里每个词去"看"其他所有词，按相关度加权吸收信息，更新自己。"苹果手机"和"吃苹果"里的"苹果"因此得到不同表示。

**QKV 三角色（图书馆类比）**：
- **Q(Query)**：我想找什么（带着需求找书）
- **K(Key)**：各词的标签（书脊标签，供匹配）
- **V(Value)**：各词的实际内容（书里内容，按匹配度抄进笔记）

**公式四步**：`Attention(Q,K,V) = softmax(QKᵀ/√dₖ)·V`
1. `QKᵀ`：Q 和所有 K 点积 → 相关度分数矩阵 `[n,n]`
2. `÷√dₖ`：缩放，防高维点积过大把 softmax 推入饱和区（→梯度消失）
3. `softmax`：每行归一成和为 1 的注意力权重
4. `×V`：按权重加权所有词的 V → 融合上下文的新向量

"Self" = QKV 都来自同一序列（对比 Cross-Attention：Q 来自一序列、K/V 来自另一序列）。

## 核心要点

### Multi-Head 多头注意力
- 复制多份注意力并行做，每头维度更小、各学一种关注模式（指代/语法/修饰…），拼接后过 Wo 融合。
- 比单头全面，且每头维度缩小 → **总算力不变的"免费多样性"**。

### 残差 + LayerNorm（让深层训得动）
- **残差**：`out = x + Sublayer(x)`，给梯度一条高速路，缓解梯度消失；子层只学"变化量"。
- **LayerNorm**：归一化激活到均值0方差1，稳定训练。是 Layer（对特征维）不是 Batch（序列变长，BatchNorm 不适用）。
- **Pre-LN**（`x+Sublayer(LN(x))`，现代主流，易训）vs **Post-LN**（原论文，效果略好但深层难训）。

### FFN 前馈网络
- 两层全连接+激活：`W2·act(W1·x)`，先升维再降维（如 512→2048→512）。
- **逐位置独立**：每个词各过各的。分工——**Attention 让词互看，FFN 让每个词深加工**。

### 位置编码
- Self-Attention 是集合操作、本身无序，"猫追狗"vs"狗追猫"看起来一样 → 必须注入位置。
- **绝对(Sinusoidal)**：位置向量加到词向量上；相对位置感知弱、外推差。
- **RoPE(主流)**：按位置旋转 Q/K，使注意力点积只依赖**相对距离**；外推好、相对位置感知强（LLaMA/Qwen）。

### Encoder / Decoder / Decoder-only
| 架构 | 代表 | 注意力 | 擅长 |
|------|------|--------|------|
| Encoder-only | BERT | 双向 | 理解：分类/检索/抽取 |
| Decoder-only | GPT/LLaMA/Qwen | 单向(因果掩码) | 生成：续写/对话 |
| Encoder-Decoder | T5/原始 | 双向+单向+交叉注意力 | 翻译/摘要 |
- **因果掩码**：第 i 词只能看 1~i，未来位置分数设 -∞，softmax 后为 0，防"偷看未来"作弊。
- **为何主流 Decoder-only**：训练目标简单统一（预测下一 token，海量无标注文本即数据）、规模化好、生成任务通用。

### KV Cache（推理加速，面 Gateway 必问）
- 自回归生成一次吐一个 token，每步都要新词 Q 对前文所有 K/V 做注意力。
- **前文的 K/V 之前已算过** → 缓存起来复用，只算新词的 K/V 并追加。复杂度 O(n²)→O(n)。
- **只缓存 K/V 不缓存 Q**：Q 是当前词的查询、用完即弃；K/V 代表历史信息、被后续每步反复用。
- **显存权衡**：缓存 ≈ `层×头×序列长×头维×2×batch`，随**序列长和 batch 线性增长**，是长上下文推理的显存瓶颈 → PagedAttention(vLLM，模块06) 专门优化它。

## 动手记录

`experiments/self-attention/single_head.py`（复用 numpy 环境）：手写单头 self-attention，把 `softmax(QKᵀ/√dₖ)·V` 四步跑出真实数值。

- ③ softmax 权重每行和=1 ✅；④ 输出形状 `[4,8]` 与输入一致 → 可堆叠下一层。
- **√dₖ 缩放对比实证**：缩放后"猫"权重 `[0,0.989,0.011,0]`（平滑）；不缩放 `[0,1,0,0]`（彻底 one-hot、饱和）→ 印证不缩放会梯度消失。

## 完整结构图（Decoder-only Block × N）

```
              输入 tokens
                  │
        Token Embedding + 位置编码(RoPE)
                  │
   ┌──────────────▼───────────────┐
   │ Transformer Block × N 层       │
   │  x ─┬ LayerNorm─Multi-Head Attn┐  ← 因果掩码 + KV Cache
   │     └────── 残差 + ───────────┘  │
   │  x ─┬ LayerNorm─FFN(升维→激活→降维)┐
   │     └────── 残差 + ───────────┘  │
   └──────────────┬───────────────┘
                  │
             最终 LayerNorm
                  │
        线性层 + softmax → 下一 token 概率
```
口诀：**Embedding+位置 → [注意力(残差+LN) → FFN(残差+LN)] × N → 输出头**。

## 踩过的坑 / 易混淆点

- **√dₖ 缩放不是可选项**：不缩放 softmax 饱和、梯度消失，代码里已实测差异。
- **LayerNorm ≠ BatchNorm**：NLP 序列变长，用 LayerNorm。
- **只缓存 K/V 不缓存 Q**：想清楚"谁会被后续复用"。
- **注意力本身无序**：位置信息是额外加的，别以为注意力自带顺序。
- **Multi-Head 不增算力**：每头维度缩小，总量守恒。

## 面试问答（自测）

- Q: Q/K/V 分别是什么？为何除以 √dₖ？
  A: Q=查询、K=标签、V=内容；用 Q·K 算相关、softmax 成权重、加权 V。高维点积数值大会让 softmax 饱和、梯度消失，√dₖ 缩放稳住训练。
- Q: Multi-Head 相比单头的好处？
  A: 并行学多种关注模式更全面；每头维度小、总算力不变。
- Q: 为什么主流 Decoder-only？
  A: 训练目标简单统一、海量无标注文本即数据、规模化好、生成任务通用。
- Q: RoPE 相比绝对编码解决了什么？
  A: 旋转 Q/K 使注意力只依赖相对距离，相对位置感知强、长度外推好。
- Q: KV Cache 缓存什么？为何加速？对显存影响？
  A: 缓存历史 K/V，避免自回归重算前文，O(n²)→O(n)；代价是显存随序列长/batch 线性增长，是长上下文瓶颈。

## 参考资料

- Attention Is All You Need（原论文）
- The Illustrated Transformer（Jay Alammar）
- Andrej Karpathy: nanoGPT
- RoPE、PagedAttention(vLLM) 相关资料
