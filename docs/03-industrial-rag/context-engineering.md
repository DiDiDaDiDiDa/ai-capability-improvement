# L5 · 上下文工程：检索之后修「喂给 LLM 的上下文」

> 实验：`experiments/rag-context-eng/context_eng_demo.py`（纯标准库，Parent-Child / Compression / Lost-in-middle 全绿）

## 这一层修的是哪个环节

```
用户提问 ──▶ [L4 Query] ──▶ 检索(L2) ──▶ 精排(L3) ──▶ [L5 上下文工程] ──▶ LLM
                                                    ↑ 本层
```

- **L4 Query** 修「提问本身」：发生在**检索之前**。
- **L2 Hybrid** 修「召回通道」：向量漏关键词，补 BM25。
- **L3 Rerank** 修「候选内的序」：粗召回排序噪声。
- **L5 Context** 修「喂进 LLM 的上下文」：发生在**检索之后**——块太大 / 噪声句 / 关键信息掉中间。

一句话边界：**L4 改输入，L2 改召回，L3 改排序，L5 改上下文形状。四者正交，可叠加。**

## 为什么需要：上下文侧的三类硬伤

| 硬伤 | 例子 | 后果 |
|------|------|------|
| 检索粒度 vs 生成粒度冲突 | 整篇 embed 太粗，句级太碎 | 检索不准，或 LLM 缺上下文 |
| 相关块夹杂噪声句 | 差旅制度里夹着加班/餐饮条款 | 浪费 token，模型被噪声带偏 |
| Lost-in-the-middle | gold 落在中间位置 | 长上下文 U 型注意力，中间信号被忽略 |

L1–L4 解决「找对文档」；找对了仍可能**喂错形状**——这就是 L5。

## 三个抓手

### 1. Parent-Child Retrieval — 小块检索、大块生成

- **Child**（句子）：检索单元，粒度细，专名/数字信号清晰。
- **Parent**（整篇/段落）：生成单元，上下文完整，喂给 LLM。
- 流程：Hybrid 检 child → 去重上卷 parent → 返回完整父块。

**实验抓手**：`ParentChildStore` 用 **Hybrid(BM25+Vector+RRF)** 检 child（与 L2/L3/L4 对齐）。
纯向量在短句上 n-gram 哈希稀疏、碰撞严重（「VPN」题会漂到「病假」句）——句子粒度尤其依赖 BM25 关键词强信号。

| 对照 | top1 命中 |
|------|:---------:|
| Parent-Child（Hybrid child） | **3/3** |
| Flat-Doc（整篇大块） | 3/3 |

本语料上 Flat-Doc 也 3/3（文档少、主题分离），但 child 命中句已钉死答案所在句（如「500 元」「VPN」），上卷 parent 保证完整上下文——生产语料文档更密时，小块检索优势会放大。

生产等价物：LlamaIndex `AutoMergingRetriever` / LangChain `ParentDocumentRetriever`。

### 2. Context Compression — 压掉无关句

从 parent 里按 query 相关性挑 top 句，丢掉噪声句，省 token 降噪。

| 指标 | 数值 |
|------|------|
| 原 parent tokens | 104 |
| 压缩后 tokens | 34（**33%**） |
| 答案句 | 「一线城市每晚不超过 **500** 元」保留 |

教学版：词覆盖 + 字符 bigram Jaccard 打分。生产等价物：LLMLingua / LongLLMLingua / Cross-Encoder 句级过滤。

### 3. Lost-in-the-middle — U 型注意力 + 重排缓解

Liu et al. 2023：长上下文注意力呈 **U 型**——首尾高、中间低。gold 掉中间会被忽略。

教学化位置权重：`w(pos) = 0.4 + 0.6 * |2x - 1|`（两端 1.0，中间 ~0.4）。

缓解：把高相关块排到两端（最相关放头，次相关放尾，其余塞中间）。

| 策略 | gold 位置权重 | 有效信号 Σ(rel×w) |
|------|:-------------:|:-----------------:|
| naive（gold 居中） | 0.40 | 1.135 |
| reorder（gold 置头） | **1.00** | **1.675** |

## 实验数据

```
Parent-Child top1  3/3 | Flat-Doc 3/3
Compression        104 → 34 tokens（33%），答案「500」保留
Lost-in-middle     有效信号 1.135 → 1.675（gold 权重 0.40 → 1.00）
```

pipeline：`retrieve child → 上卷 parent → 压缩 → 重排两端 → 喂 LLM`

## 边界与选型

- **Child 粒度**：句子 / 小段落均可；太碎会丢跨句指代，太粗退回 Flat-Doc。
- **Child 检索必须 Hybrid**：短句纯向量在教学 n-gram 下会漂——生产 BGE 也建议保留稀疏通道。
- **压缩过激**：keep 太小会砍掉必要限定条件（「未经批准拒报」），要按题型调 keep。
- **Lost-in-middle 与 K**：进 prompt 的块数 K 越大，中间陷阱越深；K≤5 时重排收益有限，K≥10 必须处理。
- **与 L3 的分工**：Rerank 改「谁先进上下文」；L5 改「上下文内部形状」。Rerank 之后仍可压缩与重排。

## 面试题自测

1. Parent-Child Retrieval 解决什么问题？child 和 parent 各承担什么角色？
2. 为什么 child 检索不能退化成纯向量？
3. 「Lost in the middle」是什么？怎么缓解？
4. Context Compression 和 Rerank 有什么区别？
