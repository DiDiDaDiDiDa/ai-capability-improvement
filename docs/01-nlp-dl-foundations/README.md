# 模块 01 · NLP 与深度学习基础

> 预计 20h ｜ 对应学习方案第一阶段

## 学习目标

不追求理论深度，但要把工程一线天天碰的底层概念吃透：Token、Embedding、Transformer、KV Cache、采样参数。目标是**能画图、能手写最小实现、能在面试里讲清楚**。

## 知识地图

```
文本 ──Tokenizer──▶ Token IDs ──Embedding──▶ 向量
                                              │
                                    ┌─────────▼─────────┐
                                    │   Transformer      │
                                    │  Self-Attention    │
                                    │  Multi-Head + FFN  │
                                    │  Residual+LayerNorm│
                                    └─────────┬─────────┘
                                              │
                            Prefill / Decode（自回归 + KV Cache）
                                              │
                                采样（Temperature/TopP/TopK）──▶ 输出 Token
```

## 核心概念清单

### 1. 分词 Tokenization
- Token 为什么 ≠ 字/词；子词（subword）的意义
- BPE / WordPiece / SentencePiece（Unigram）原理与区别
- 为什么 GPT 用 BPE；Qwen 等中文友好模型 tokenizer 的差异
- 词表大小、OOV、特殊 token（BOS/EOS/PAD）

### 2. Embedding
- 向量表示语义的直觉；分布式表示
- 相似度度量：Cosine / L2 / Dot Product，各自适用场景
- 为什么检索用 Embedding；embedding 模型 vs 生成模型的向量

### 3. Transformer（重点）
- Self-Attention：QKV 的来源、缩放点积、softmax
- Multi-Head Attention 为什么有效
- Residual、LayerNorm（Pre-LN vs Post-LN）、FFN
- Encoder / Decoder / Decoder-only 的区别与主流选择
- Position Encoding：绝对编码 vs RoPE

### 4. 推理与 KV Cache
- Prefill / Decode 两阶段
- KV Cache 缓存了什么、为什么能省算力、和显存的权衡
- 采样：Temperature、Top-P、Top-K、贪心/采样
- Stop、max_tokens、Structured Output、Tool Call 的推理侧含义

## 建议产出物

- [ ] 一张手绘/画图工具画的完整 Transformer 结构图（放 `docs/01-nlp-dl-foundations/`）
- [x] 手写最小 BPE：训练 + 编码（`experiments/tokenizer-bpe/mini_bpe.py`）
- [x] tiktoken 实跑：中英文 token 数对比（`experiments/tokenizer-bpe/demo_tiktoken.py`）
- [ ] 手写单头 self-attention（numpy 即可）
- [ ] 采样参数对比实验：同 prompt 不同 temperature/top_p 的输出

## 面试高频题（出口自测）

1. Token 和字符/词是什么关系？为什么模型按 token 计费？
2. BPE 的训练过程？为什么用子词而不是整词？
3. Self-Attention 的 Q、K、V 分别是什么？为什么要除以 √dₖ？
4. Multi-Head 相比单头的好处？
5. KV Cache 缓存的是什么？为什么能加速？对显存有什么影响？
6. Temperature 和 Top-P 分别怎么影响输出？都调到 0 会怎样？
7. 为什么现在主流大模型是 Decoder-only？
8. RoPE 相比绝对位置编码解决了什么问题？

## 资源

- Attention Is All You Need（原论文）
- The Illustrated Transformer（Jay Alammar）
- Andrej Karpathy: Let's build the GPT Tokenizer / nanoGPT
- Hugging Face Tokenizers 文档

## 检查清单

- [ ] 能默画 Transformer 结构图并讲清每个模块作用
- [ ] 能手写 BPE 和 self-attention
- [ ] 能讲清 KV Cache 的原理与显存权衡
- [ ] 能回答上面全部面试题
