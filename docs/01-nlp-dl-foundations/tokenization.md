# 分词 Tokenization（Day 1）

> 所属模块：01 · NLP 与深度学习基础 ｜ 学习日期：2026-07-08

## 一句话总结

Tokenization 是大模型的"输入门"：模型只认数字，分词器把文本切成 token（子词单位）再映射成整数 ID。计费、上下文长度、"中文比英文贵"都由这一层决定。

## 我的理解

```
"我爱学习AI" ──分词器──▶ ["我","爱","学习","AI"] ──查词表──▶ [1234,567,8901,42] ──▶ 模型
   文本                     tokens                       token IDs
```

Token 既不是字符也不是词，而是**子词（subword）**，是对两种朴素切法的折中：

- **字符级**：词表小、无 OOV，但序列太长、单字符没语义 → 算力浪费。
- **词级**：语义完整、序列短，但词表爆炸 + 遇到新词只能 `[UNK]`（OOV）。
- **子词级（现代方案）**：高频词整体保留，低频/生僻词拆成片段。词表可控（几万~十几万）、几乎无 OOV、常用词不被切碎。

核心洞察：**训练时只学"子词积木"，编码时用积木拼任何新词**——这就是子词方案同时解决"词表爆炸"和"OOV"的原因。

## 核心要点

- **BPE（GPT 系）**：训练 = 反复合并**频率最高的相邻符号对**，直到词表满。高频组合像滚雪球越合越大。
- **字节级 BPE（GPT-2+）**：在原始字节(0-255)上做 → 任何字符都是字节序列，**OOV 彻底为 0**；代价是一个汉字占 2-3 字节，**中文更费 token**。
- **WordPiece（BERT 系）**：合并判据不同——选"合并后让语料**似然提升最多**"的对，而非单纯最高频。
- **Unigram / SentencePiece**：反向——先建大词表，**逐步删掉影响最小的子词**；空格也当普通字符(`▁`)，不依赖预分词，**对中文/日文友好**。
- **中文模型（Qwen 等）**：底层仍是 BPE 类，差异在**词表针对中文优化**（常见汉字/词直接收进词表）→ 中文更省 token。
- **特殊 token**：BOS/EOS（序列起止，生成到 EOS 即"说完"）、PAD（补齐 batch）、UNK（子词方案下极少用）、对话角色标记（`<|im_start|>` 等）。

## 动手记录

代码在 `experiments/tokenizer-bpe/`：

**1. `demo_tiktoken.py`** — 用真实分词器 cl100k_base（词表 100277）观察：
- `tokenization` → `['token','ization']`：BPE 把长词拆成有意义的高频子词。
- `unhappiness` → `['un','h','appiness']`：切分由**统计频率**决定，不按语义，有时不"优雅"。
- 中英对比（关键实证）：
  - 英文 `I love learning artificial intelligence`（5 词）→ **5 tokens**
  - 中文 `我爱学习人工智能`（8 字）→ **11 tokens**（比字数还多）
  - 印证"中文更费 token"：英文词表下汉字平均约 1.4 token/字。

**2. `mini_bpe.py`** — 手写训练+编码，语料 `low/lower/newest/widest`：
- 训练：`e+s→es→est→est</w>`（freq=9 先合），最后 `new+est</w>→newest</w>` 整词成 1 token。
- 编码 OOV 验证：训练里**没有** `lowest`，但用学过的 `low`+`est</w>` 拼出 → `['low','est</w>']`；`slowest`→`['s','low','est</w>']`。**永不产生 UNK。**

## 踩过的坑 / 易混淆点

- **中文乱码 `�`**：tiktoken 把某些汉字切成两个 token，单个 token 是"半个汉字的字节"，无法显示成完整字 → 现象是字节级 BPE 的直接结果，不是 bug。
- **Token ≠ 字 ≠ 词**：面试最爱问。别把"一个 token = 一个词"当默认，尤其中文一个字可能 ≥1 token。
- **BPE 切分不按语义**：`unhappiness` 里 `h` 单独成 token 就是例子；切法完全由训练语料频率决定。
- **环境坑**：macOS 系统 Python 装包被 PEP 668 拦截，用 `python3 -m venv .venv` 建虚拟环境再装 tiktoken；`.venv/` 已在 `.gitignore` 忽略。

## 面试问答（自测）

- Q: Token 和字符/词是什么关系？为什么按 token 计费？
  A: token 是子词，介于字符和词之间。模型算力和上下文长度都以 token 为单位，一次 forward 处理 token 序列，长度直接决定开销，故按 token 计费。
- Q: BPE 训练过程？为什么用子词而非整词？
  A: 从字符/字节起步，反复统计并合并频率最高的相邻对，直到词表达标。用子词是为同时解决词表爆炸（有限词表覆盖无限词汇）和 OOV（生僻词用子词拼出，不丢信息）。
- Q: 为什么中文比英文费 token？中文模型怎么优化？
  A: 字节级 BPE 下一个汉字占 2-3 字节、常拆成多 token；英文为主的词表对中文覆盖不足。中文模型（Qwen 等）把常见汉字/词收进词表来省 token。
- Q: BPE / WordPiece / Unigram 的区别？
  A: BPE 合并最高频对；WordPiece 合并"似然提升最多"的对；Unigram 从大词表删到小。SentencePiece 把空格当字符、不依赖预分词，适合中文。

## 参考资料

- Andrej Karpathy: Let's build the GPT Tokenizer
- Hugging Face Tokenizers 文档
- tiktoken（OpenAI 官方 BPE 库）
