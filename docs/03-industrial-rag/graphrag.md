# L6 · GraphRAG：找「连」的实体，补向量只找「像」的洞

> 实验：`experiments/rag-graphrag/graphrag_demo.py`（纯标准库，抽取 / Local 多跳 / Global 社区全绿；Graph 3/3 vs Vector 2/3，含 1 道 flip）

## 这一层修的是哪个环节

```
用户提问 ──▶ L4 Query ──▶ 检索 ──┬── L2 向量/Hybrid：找「像」的块
                                └── L6 图谱：找「连」的实体/社区  ──▶ 融合 ──▶ L3/L5 ──▶ LLM
                                         ↑ 本层
```

- **L2 Hybrid** 修召回通道：关键词 + 语义，仍是**块相似度**。
- **L6 GraphRAG** 修**跨块关系与全局主题**：实体边多跳、社区摘要——相似度够不着的「引用/归属/因果」。

一句话边界：**向量找像的块，图谱找连的实体。互补，不是替换。**

## 为什么需要：向量检的三类硬伤

| 硬伤 | 例子 | 后果 |
|------|------|------|
| 跨块关系 | 差旅页写「调休规则见人事制度」，答案在 hr 页 | 向量贴引用句所在页，漏权威页 |
| 多跳推理 | A→B→C，证据分散 | 单块相似度拼不出路径 |
| 主题/全局问 | 「人事制度整体要点」 | 向量贴局部句，缺社区级汇总 |

微软 GraphRAG 的核心洞察：局部检索（local）走实体邻域，全局检索（global）走社区摘要。本实验用内存图教学化这两路。

## 三个抓手

### 1. 实体 + 关系抽取 → 建图

- 教学版：别名表 + 句内共现关系模板（可热替换 LLM/NER）。
- 边：`(头) -[关系]-> (尾) @source_doc`。
- **本体落地**：抽象节点（如「人事制度」）挂到权威文档 `hr-leave.md`——正文只有「见人事制度」时，多跳终点才能落到真正有规则的页。

实验：15 实体 / 13 三元组 / 3 社区（travel / hr / security）。

### 2. Local 多跳检索

种子实体（query 抽实体）→ BFS 多跳 → 文档计分（跳数衰减 + 种子间边证据 + 本体落地加成）。

| Query | Graph top1 | Vector top1 |
|-------|:----------:|:-----------:|
| 调休规则见的人事制度里年假怎么规定 | **hr-leave** HIT | policy-travel **MISS**（flip） |
| X-KEY-99 谁能轮换 | it-security HIT | it-security HIT |
| 公共 Wi-Fi 要开什么 | it-security HIT | it-security HIT |
| **合计** | **3/3** | **2/3**（1 flip） |

flip 钉死因果：向量贴「调休/人事」字面密集的差旅页；图谱沿 `差旅→人事制度` 边 + 本体落地到 hr 页。

### 3. Global 社区检索

社区 = 主题种子 + 一跳扩张（教学版 Louvain 的可读替代）。用**社区摘要**向量 + 实体重合打分。

| Query | 命中社区 | 社区文档 |
|-------|----------|----------|
| 人事相关制度整体有哪些要点 | community-hr | hr-leave + policy-travel（关联边） |

向量 top1 仍是 policy-travel（局部贴边）；Global 先给社区摘要，再上卷社区文档——主题问不该只返回单句。

## 与纯向量的互补边界

| 题型 | 谁够用 | 说明 |
|------|--------|------|
| 字面专名（`X-KEY-99`） | 向量已够 | 图谱不抢功，两边都 hit |
| 跨页引用 / 多跳 | **图谱** | flip 场景 |
| 主题汇总 | **Global 社区** | 摘要级，非整库扫块 |

**选型**：有明确实体关系、制度交叉引用、要做全局主题报告 → 上 GraphRAG；纯 FAQ 字面题 → Hybrid 即可，别为图谱而图谱。

## 生产映射

| 教学组件 | 生产等价物 |
|----------|------------|
| 别名表 + 关系模板 | LLM 结构化抽取 / spaCy NER + RE |
| 内存 `adj` + triples | Neo4j / NetworkX / FalkorDB |
| 社区种子扩张 | Leiden / Louvain community detection |
| 社区摘要 | LLM map-reduce 摘要（微软 GraphRAG 流水线） |
| Local BFS 计分 | 带权随机游走 / Personalized PageRank |

## 面试题自测

1. 什么场景该上 GraphRAG 而不是普通向量检索？
2. Local 与 Global 检索各解决什么问题？
3. 为什么「见人事制度」这类引用句会让向量检错页？本体落地起什么作用？
4. GraphRAG 的主要代价是什么？（抽边成本、图维护、延迟）

## 实验复现

```bash
cd experiments/rag-graphrag && python3 graphrag_demo.py
```

pipeline：`extract → graph → local multihop | global community → 喂 LLM`
