# 推理与采样（Day 4）

> 所属模块：01 · NLP 与深度学习基础 ｜ 学习日期：2026-07-08

## 一句话总结

模型每步只给出词表上的概率分布，推理负责"挑哪个 token、怎么挑、何时停"：Prefill/Decode 两阶段跑生成，Temperature/Top-P/Top-K 控制随机性，EOS/stop/max_tokens 控制停止。

## 我的理解

```
模型前向 → logits → softmax → 概率分布
                                 │
        采样策略(temperature/top-p/top-k) 挑一个 token
                                 │
        追加到序列 → 再前向 → ... → 遇到 stop/EOS 才停
```

### Prefill / Decode 两阶段
- **Prefill（预填充）**：把整个输入 prompt **一次性并行**过模型，算好所有位置的 K/V 填进 KV Cache。计算密集、快，决定**首 token 延迟(TTFT)**。
- **Decode（解码）**：从第一个新词起，**每次只算一个 token**（新词 Q 配 KV Cache 全部历史 K/V），追加后循环。访存密集、串行、慢，决定**吐字速度(TPOT)**。
- 两阶段瓶颈不同（Prefill 拼算力，Decode 拼显存带宽）→ 模块06 的 Continuous Batching 就是优化 Decode 阶段 GPU 利用率。

```
Prefill: [今天][天气][怎么][样][?] ─并行,填KV Cache─▶ 生成"今"
Decode:  "今"→"天"→"很"→"好"→[EOS]  ─每次一个,复用KV Cache─▶ 停
```

## 核心要点

### 采样策略
- **Greedy 贪心**：永远选概率最高的。确定可复现，但呆板、易重复（"的的的"死循环）。
- **Temperature 温度**：`softmax(logits/T)`。T<1 分布变尖→保守确定；T>1 变平→随机有创意；T→0 退化成贪心。
- **Top-K**：只保留概率最高的 K 个，在其中采样。缺点：K 固定，不随分布形状自适应。
- **Top-P 核采样**：按概率从高到低累加到 P 为止的**最小集合**里采样。截断数量**动态**（尖锐分布留少、平缓分布留多）→ 比 Top-K 更自适应，最常用。
- 实践常 `temperature + top-p` 组合：先调分布形状，再截断长尾。

```
Top-P=0.9: 好(0.5)→0.5, 不错(0.2)→0.7, 棒(0.15)→0.85, 还行(0.08)→0.93停
           → 在 {好,不错,棒,还行} 里采样
```

### 停止与输出控制
- **EOS**：模型生成到结束 token 自然停。
- **stop / stop sequences**：指定停止串（如 `"###"`），生成到它就截断。
- **max_tokens**：输出 token 硬上限，控成本防失控；输入+输出不能超上下文窗口。
- **JSON Mode / 结构化输出**：约束解码——每步把不合 JSON 语法的 token 概率置 0，保证可解析（模块02）。
- **Tool Call / Function Calling**：受约束地生成"工具名+参数JSON"，外部解析执行（模块04）。
- 一句话：EOS/stop/max_tokens 管"何时停"，JSON Mode/Tool Call 管"生成什么格式"。

## 动手记录

`experiments/sampling/sampling_demo.py`（纯 numpy，不依赖模型/API）：固定一组 logits，对比各采样策略。

- **Temperature 调尖锐度**：T=0.3 时"好"占 0.918（近乎独占）；T=1.0 占 0.499；T=2.0 压到 0.310，连长尾"🤔"都有 0.025 机会 → 温度确实在改分布形状。
- **Top-K vs Top-P**：此分布下 `top_k=2` 与 `top_p=0.7` 恰好都留 2 个、结果相同，但机制不同——K 的 2 是**写死**的，P 的 2 是**累积到 0.7 算出来**的；分布更平时 Top-P 会自动多留，Top-K 仍死板。
- **反复采样看多样性**：贪心 12 次全是"好"（呆板）；T=0.3 偶尔蹦"不错"；T=2.0 出现"烂/一般/还行"各种花样（发散但开始跑偏）。→ 印证事实任务调低温、创意任务调高温。

## 踩过的坑 / 易混淆点

- **Temperature 和 Top-P 是两种不同机制**：温度改**分布形状**，Top-P 改**候选范围**，可叠加。
- **max_tokens 只限输出**：别忘了输入 token 也占上下文窗口。
- **贪心≠最优整句**：每步选最高不保证整句概率最高（局部贪心），也是重复的根源。
- **两阶段别混**：Prefill 并行快、Decode 串行慢，KV Cache 主要服务 Decode。

## 面试问答（自测）

- Q: Temperature 和 Top-P 分别怎么影响输出？都调到 0/贪心会怎样？
  A: Temperature 调分布尖锐度（低→确定保守，高→随机创意）；Top-P 按累积概率动态截断候选集再采样。趋 0/贪心时输出确定可复现，但呆板易重复。
- Q: Top-K 和 Top-P 区别？
  A: Top-K 固定保留前 K 个；Top-P 保留累积到 P 的最小集合，数量随分布自适应，更常用。
- Q: Prefill 和 Decode 有什么不同？
  A: Prefill 并行处理输入、算力密集、定 TTFT；Decode 每步一个 token、访存密集、串行、定 TPOT。
- Q: 怎么让模型稳定输出合法 JSON？
  A: 约束解码，每步把不符合 JSON 语法的 token 概率置 0。

## 参考资料

- OpenAI / Anthropic API 参数文档（temperature/top_p/stop/max_tokens）
- The Curious Case of Neural Text Degeneration（Top-P/核采样论文）
- vLLM 关于 Prefill/Decode、Continuous Batching 的文档
