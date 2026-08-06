# Experiments · 实验与评测

记录 AI 能力实验设计、评测样例、运行结果和改进结论。

## 运行与依赖

绝大多数实验**纯 stdlib，直接 `python3 <脚本>.py` 即可**，不需要装任何东西。
只有下列 4 个需要第三方库，各自目录下有 `requirements.txt`（版本已钉扎）：

| 实验目录 | 依赖 | 备注 |
|---------|------|------|
| `self-attention/` | numpy | 轻量，秒级装完 |
| `sampling/` | numpy | 轻量，秒级装完 |
| `tokenizer-bpe/` | tiktoken | 仅 `demo_tiktoken.py` 需要；`mini_bpe.py` 纯 stdlib。首次运行联网下载编码表 |
| `mini-semantic-search/` | numpy + sentence-transformers | **最重**：拖入 torch，首次运行需联网下载约 470MB 模型，会长时间阻塞在加载（不是卡死） |

统一装法（在对应实验目录下）：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python <脚本>.py
```

`.venv/` 已在 `.gitignore` 中，不入版本库——所以换机器/新克隆必须按上面重建。

## 建议组织方式

按模块或项目建子目录，例如：
- `tokenizer-bpe/`：手写 BPE 实验
- `sampling/`：采样参数对比
- `naive-rag/`：L1 Naive RAG 全链路（chunk/embed/retrieve/grounded）
- `rag-hybrid-vs-naive/`：L2 Hybrid（BM25 + Vector + RRF）vs Naive 召回对照
- `rag-rerank/`：L3 粗召回 + Cross 精排（MRR/Top-1 翻盘，教学 scorer）
- `rag-query-opt/`：L4 Query 优化（Rewrite / HyDE / Multi-Query / Self-Query，四路翻盘对照）
- `rag-context-eng/`：L5 上下文工程（Parent-Child / Compression / Lost-in-middle）
- `rag-graphrag/`：L6 GraphRAG（实体关系抽取 / Local 多跳 / Global 社区，对照纯向量 flip）
- `mini-agent/`：模块 04 Mini Agent（ReAct Loop / Memory / Plan / Tool Schema / Supervisor-Worker）
- `finetune-eval/`：模块 05 微调与评估（LoRA 参数量/前向、QLoRA 存储、SFT/DPO 定位、选型、BLEU/ROUGE/Judge 偏差）

## 单个实验建议格式

```
# <实验名>
目的：想验证什么
设置：数据 / 模型 / 参数
过程：怎么做的
结果：数据 / 截图 / 表格
结论：学到了什么，下一步
```
