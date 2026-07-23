# Serving 四大机制：KV Cache / Continuous Batching / PagedAttention / Speculative Decoding

> 所属模块：06 · AI Infra ｜ 学习日期：2026-07-22
> 实验：`experiments/ai-infra/serving_demo.py`（四机制全绿 EXIT:0）

## 一句话总结

推理服务化的吞吐/显存优化围绕一件事转：**KV Cache 用显存换算力**，于是
**Continuous Batching** 抢利用率、**PagedAttention** 抢显存、**Speculative Decoding**
抢延迟——vLLM 的护城河就是把这三招做到极致。

## 我的理解

```
自回归解码天生串行、访存密集。优化四层：
  KV Cache            ── 别重算历史 K/V（前提，其它三招都建在它上面）
  Continuous Batching ── 别让空 slot 空转（吞吐）
  PagedAttention      ── 别为 KV 连续预留（显存 → 并发数）
  Speculative Decoding── 别一次只出一个 token（延迟）
```

### 1. KV Cache：为什么必须缓存

自回归第 t 步要对前面所有 token 算注意力。**没缓存**：每步把历史 K/V 全部重算，
成本随序列长度平方级涨；**有缓存**：历史 K/V 存下来，每步只算「新 query 对全序列」。

- 实验：prompt=128 生成=64，**无缓存 17 亿 vs 有缓存 1051 万，162x**
- 代价：显存 = `2 * layers * heads * head_dim * seq * batch`（K 和 V 各一份）
- **KV Cache 是后面三招的地基**——正因为它吃显存，才需要 paging 管理它

### 2. Continuous Batching：静态 batch 的空转账

**静态 batching**：凑齐一批一起算，必须等批内**最长**的请求跑完才能换下一批——
短请求早早完成，slot 却空转到批结束。**Continuous（in-flight）batching**：每一步
（每个 decode step）检查谁完成了，立刻把等待队列的新请求填进空出的 slot。

- 实验：64 个长短不一请求，batch=8
  - 静态：896 步，GPU 利用率 **33.8%**
  - 连续：348 步，利用率 **86.9%**，吞吐 **2.57x**
- 粒度关键：调度发生在 **iteration 级**（每个 token step），不是 request 级

### 3. PagedAttention：KV 显存分页

**朴素方案**：给每个请求按 `max_len` 连续预留 KV 空间 → 大量**内部碎片**
（请求实际只用 30 token，却占了 512 的坑）。**PagedAttention**：把 KV 切成固定大小的
**块（block/page）**，按需分配；用**块表（block table）**记录逻辑位置→物理块的映射，
物理上可以不连续。

- 实验：8 个请求真实长度 10~500，block_size=16
  - 朴素预留：4096 slot，浪费 **67%**
  - 分页按需：1424 slot，浪费 **4%**，省 **65%** 显存
- **和 OS 虚拟内存的类比**（面试必答）：
  | OS 虚拟内存 | PagedAttention |
  |------------|----------------|
  | 进程逻辑地址连续 | 请求 KV 逻辑连续 |
  | 物理页帧可不连续 | 物理 KV 块可不连续 |
  | 页表映射 | 块表(block_table)映射 |
  | 按需换页 | 按需分配块 + 块耗尽时 preemption/swap |
- 附带红利：块可**共享/copy-on-write**（多 beam、prefix 共享 prompt 时省显存）
- 碎片上界：每个请求最多浪费不足一个 block（只剩最后一块的零头）

### 4. Speculative Decoding：草稿 + 验证

小的**草稿模型**一次猜 k 个 token，大的**目标模型**用**一次前向**并行验证这 k 个，
从首个不匹配处截断、接受匹配前缀 + 补 1 个纠正 token。关键：验证 k 个 token 只花
大模型 **1 次前向**，而逐 token 解码要 k 次。

- 实验：生成 200 token，k=4
  - 命中率 0.9：大模型前向 200 → **54，加速 3.70x**
  - 命中率 0.5：大模型前向 200 → **106，加速 1.89x**
- **正确性保证**：输出分布和纯大模型解码**一致**（大模型验证是权威裁判）
- **什么时候收益大**：草稿命中率高（草稿模型和大模型分布接近）+ 大模型前向是瓶颈
- **什么时候亏**：命中率低时草稿白算，反而增加总计算量

## 动手记录

```bash
python3 experiments/ai-infra/serving_demo.py
# KV 162x | 连续 batch 利用率 33.8%→86.9% 吞吐 2.57x
# 分页省 65% 显存 | 投机 200→54 前向 3.70x | EXIT:0
```

## 踩过的坑 / 易混淆点

- **KV Cache ≠ Semantic Cache**：前者是推理层「同一次生成内」缓存历史 K/V（算子级）；
  后者是 Gateway 层「跨请求」按语义相似命中整个响应（应用级）。两回事,别混。
- **Continuous batching 调度在 request 级**：错。调度在 **iteration/token 级**才是精髓。
- **PagedAttention 消除所有浪费**：不是，仍有每请求最后一块的零头（< 1 block），
  只是从「按 max_len 预留」的巨大外部浪费降到「块内零头」的可控内部碎片。
- **投机解码能提质量**：不能，它只提**速度**，输出分布不变；命中率低还可能变慢。
- **静态 batch 的瓶颈是 batch size**：错，瓶颈是**批内最长请求**——长尾拖垮整批。

## 面试问答（自测）

- **Q: Continuous vs 静态 batching？为何吞吐高？** 静态等批内最长请求、slot 空转；
  连续在每个 token step 让完成的请求退出、立刻填新请求，利用率从 ~34% 拉到 ~87%。
- **Q: PagedAttention 解决什么？OS 类比？** 解决 KV 连续预留的内部碎片；逻辑连续/物理
  分页/块表映射，对应虚拟内存的页表，块耗尽触发 preemption 类比换页。
- **Q: Speculative Decoding 原理？何时收益大？** 草稿模型猜 k 个、大模型 1 次前向验证；
  命中率高且大模型前向是瓶颈时收益大，命中率低会亏。
- **Q: KV Cache 和 Semantic Cache 一回事吗？** 不是。推理层算子级 vs Gateway 应用级、
  单次生成内 vs 跨请求、K/V 张量 vs 整段响应。

## 参考资料

- vLLM: Efficient Memory Management with PagedAttention（原论文）
- Orca: 提出 iteration-level scheduling（continuous batching 思想源头）
- Speculative Decoding（Leviathan et al. / Chen et al.）
- 实验：`experiments/ai-infra/serving_demo.py`
