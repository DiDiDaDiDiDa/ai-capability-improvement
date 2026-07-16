# Experiments · 实验与评测

记录 AI 能力实验设计、评测样例、运行结果和改进结论。

## 建议组织方式

按模块或项目建子目录，例如：
- `tokenizer-bpe/`：手写 BPE 实验
- `sampling/`：采样参数对比
- `naive-rag/`：L1 Naive RAG 全链路（chunk/embed/retrieve/grounded）
- `rag-hybrid-vs-naive/`：L2 Hybrid（BM25 + Vector + RRF）vs Naive 召回对照
- `lora-finetune/`：LoRA 微调实验

## 单个实验建议格式

```
# <实验名>
目的：想验证什么
设置：数据 / 模型 / 参数
过程：怎么做的
结果：数据 / 截图 / 表格
结论：学到了什么，下一步
```
