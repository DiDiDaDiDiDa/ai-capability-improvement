# Semantic Cache 实现说明：怎么实现 / 为什么这样 / 阈值与误命中

> 所属项目：P2 · AI Gateway ｜ 对应模块 06 ｜ 日期：2026-07-23
> 代码：`p2gateway/semantic_cache.py`，验收 `app.py` 第 6–9 段（全绿 EXIT:0）

## 一句话总结

普通 cache 按 key 精确匹配（问法改一个字就 miss）；Semantic Cache 把 query 嵌成向量，
与缓存里的向量算余弦相似度，**≥ 阈值就复用旧答案、省掉一次 LLM 调用**。阈值是灵魂：
高了命中率低，低了误命中返回错答案。

## 1. 怎么实现

```
chat(messages)
   │  取最后一条 user 消息作 query
   ▼
embed_text(query) ──► 与缓存中每条 vec 算 cosine，取最高
   │
   ├─ best_sim ≥ threshold ─► 命中：返回旧答案，标 cache=hit，不调底层
   └─ 否则 ─────────────────► 未命中：委托 inner.chat()，写回缓存，标 cache=miss
```

三个组件（`semantic_cache.py`）：

- **`embed_text`**：字符 2-gram 哈希到 128 维并归一化（与 P1 `retrieve.embed_text` 同源）。
- **`SemanticCache`**：存 `[CacheEntry(key_text, vec, value, created_at)]`；`get` 线性扫描
  求最相似 + 阈值判定 + 顺带清过期；`put` 追加并在超 `max_size` 时 FIFO 淘汰；`stats` 出命中率。
- **`CachedProvider`**：装饰器，实现 `LLMProvider.chat` 契约，套在任意 Provider（含 Router）外层。

命中/未命中都把 `cache` 字段回填进 `usage`（status/similarity/saved_call），可观测。

## 2. 为什么这样实现

### 2.1 为什么是装饰器、且套在 Router *外层*

`CachedProvider` 实现同一个 `chat` 契约 → 它包谁、被谁包都行。组合顺序有讲究：

```
CachedProvider( ModelRouter( [providers] ) )   ✅ 先查缓存，命中连"选哪个模型"都省
ModelRouter( [ CachedProvider(p) for p ] )     ❌ 每个 provider 各存一份，选型照跑
```

缓存应在**最外层**：命中就短路，选型和调用全省（验收第 9 段证明：q2 命中后
Router 不触发）。这是「省调用」的最大化。

### 2.2 为什么用最后一条 user 消息做 key

语义命中看的是**当前问的是什么**，不是整段历史。多轮对话里把全部 messages 拼进 key
会让"相同问题不同历史"永远 miss。教学取最后一条 user；生产可加"对话摘要"增强，但主键仍是当前意图。

### 2.3 为什么命中要返回拷贝

`resp = dict(cached)` 拷一份再改 usage——否则调用方拿到的是缓存内部对象的引用，改一下
就污染了缓存。这是共享可变状态的经典坑，主动规避。

## 3. 阈值与误命中（本实现最该讲的点）

### 3.1 char-ngram 是「字面相似」，不是「语义相似」

实测本实现的相似度（`app.py` 探测值）：

| 问法对 | 相似度 | 性质 |
|--------|--------|------|
| 如何重置密码 → **怎么**重置密码 | **0.778** | 同义词，语义相同 ✅ 但字面不同 |
| 北京天气 → 上海天气 | **0.750** | 不同意图，语义不同 ❌ 但字面近 |
| 如何重置密码 → 如何重置密码**？** | 0.949 | 加标点，字面几乎相同 |
| 如何重置密码 → **请问**如何重置密码 | 0.905 | 加前缀词 |

**致命观察：同义词(0.778)和异义近形(0.750)只差 0.028。** char-ngram 只看字符重合，
所以：

- 它**能**命中：加标点、加语气词、加前缀、轻微改写（字面高度重合的场景）；
- 它**不能**命中真同义词（如何=怎么），因为换头就掉字符重合；
- 它**会误命中**字面像但意图不同的（北京 vs 上海天气），如果阈值设低。

### 3.2 阈值怎么定

```
阈值 0.9  → 挡住 0.75 的误命中，也挡住 0.778 的真同义词（宁可漏，不可错）
阈值 0.7  → 能抓同义词，但 0.75 的"上海天气"也会误命中 → 返回北京答案（事故）
```

由于同义与异义的分数带**重叠**，char-ngram 下**不存在一个阈值能同时"抓全同义、挡住异义"**。
本实现选保守阈值（默认 0.9，demo 用 0.85 覆盖加前缀场景），优先**不返回错答案**。

### 3.3 生产怎么破：换真 embedding

字面 embedding 的天花板就在这。生产要真正"语义"命中：

- **embedding**：sentence-transformers / OpenAI text-embedding-3 等语义模型——「如何」和
  「怎么」在语义空间里就近，「北京」和「上海」就远，同义与异义的分数带才分得开。
- **向量存储**：Redis(RediSearch KNN)/FAISS，替掉这里的线性扫描（O(n) → ANN）。
- **兜底**：高价值场景加"命中后轻量校验"（如关键实体比对），双保险防误命中。

方法（嵌入→余弦→阈值→省调用）完全不变，只换 embedding 质量和检索结构。

## 4. TTL 与容量

- **TTL**：`ttl_s` 到期的条目在 `get` 时被清除并视为 miss（验收第 8 段）。答案会过期
  （"本月报销额度"下月就错），缓存必须能失效——知识时效性是正确性的一部分。
- **容量**：`max_size` 超出 FIFO 淘汰最旧。生产建议 LRU（按访问热度）更贴命中分布。

## 5. 踩过的坑 / 易混淆点

- **把 char-ngram 当语义**：它是字面代理，命中同义词能力有限、异义近形会误命中。要真语义换 embedding。
- **阈值一刀切**：同义/异义分数带重叠，低阈值提命中率的代价是误命中返回错答案——宁保守。
- **缓存套在 Router 内层**：每个 provider 各存一份、选型照跑，省不动。应套最外层。
- **命中返回内部对象**：不拷贝会被调用方改脏缓存。
- **答案永不过期**：时效性答案（额度/天气/库存）不设 TTL = 缓存出错答案。
- **Semantic Cache ≠ KV Cache**：前者 Gateway 层跨请求复用整段响应（应用级）；
  后者推理层单次生成内缓存历史 K/V（算子级）。见 `docs/06-ai-infra/serving-batching-paged.md`。

## 6. 面试问答（自测）

- **Q: Semantic Cache 怎么判断命中？** 嵌入 query → 与缓存向量算余弦 → ≥阈值命中，复用旧答案省调用。
- **Q: 可能出什么错？** 误命中——语义不同但向量近（尤其字面 embedding 下"上海/北京天气"），
  返回错答案；答案过期没失效；阈值过低放大误命中。
- **Q: 阈值怎么权衡？** 高=命中率低但安全，低=命中率高但危险；同义与异义分数带重叠时，
  字面 embedding 无完美阈值，优先保守 + 换真语义 embedding。
- **Q: 和 KV Cache 一回事吗？** 不是。应用级跨请求 vs 算子级单次生成内。
- **Q: 缓存该放 Router 里还是外？** 外层——命中短路，连选型带调用一起省。

## 参考资料

- 代码：`p2gateway/semantic_cache.py`、验收 `app.py`（6–9 段）
- embedding 同源：`projects/p1-enterprise-rag/p1rag/retrieve.py::embed_text`
- 对照：`docs/06-ai-infra/serving-batching-paged.md`（KV Cache vs Semantic Cache）
