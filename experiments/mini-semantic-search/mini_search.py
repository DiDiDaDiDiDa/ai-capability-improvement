"""
迷你语义检索：几句话建小向量库，query 用 cosine 找最近的。
这就是 RAG 检索的最小内核（离线建库 + 在线检索）。
对应模块 01 · Day2 产出物。

运行: python3 mini_search.py
"""
import numpy as np
from sentence_transformers import SentenceTransformer

# 一个小而好用的多语言 embedding 模型（约 120MB，支持中文）
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def cosine(a, b):
    """余弦相似度：只看方向，不看长度。"""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ---------- 1) 离线：把文档编码成向量，建"向量库" ----------
docs = [
    "猫是一种常见的家养宠物，喜欢睡觉和抓老鼠。",
    "狗是人类忠实的朋友，需要经常遛弯。",
    "宠物生病时应尽快带去动物医院就诊。",
    "Python 是一门流行的编程语言，适合做数据分析。",
    "深度学习依赖大量数据和算力来训练神经网络。",
    "北京是中国的首都，有很多历史名胜。",
]

print(f"加载模型 {MODEL} ...")
model = SentenceTransformer(MODEL)
doc_vecs = model.encode(docs)          # shape: [6, dim]
print(f"向量库建好：{len(docs)} 条文档，每条 {doc_vecs.shape[1]} 维\n")


# ---------- 2) 在线：query 编码 -> 和库里每条算 cosine -> 取最近 ----------
def search(query, top_k=3):
    q = model.encode(query)
    scores = [(cosine(q, dv), i) for i, dv in enumerate(doc_vecs)]
    scores.sort(reverse=True)          # 相似度从高到低
    print(f"Query: {query!r}")
    for rank, (score, i) in enumerate(scores[:top_k], 1):
        print(f"  #{rank}  cos={score:.3f}  {docs[i]}")
    print()


# 关键：query 用的都是"换了说法"的词，字面几乎不重合，考验语义召回
search("如何照顾生病的小猫")          # 期待命中"宠物就诊""猫"，而非字面匹配
search("神经网络怎么训练")            # 期待命中"深度学习"
search("用什么语言写数据分析脚本")     # 期待命中"Python"


# ---------- 3) 验证：归一化后 cosine ≈ 点积 ----------
print("=== 验证：向量归一化后，cosine 和点积等价 ===")
a, b = doc_vecs[0], doc_vecs[1]        # 猫 vs 狗
an, bn = a / np.linalg.norm(a), b / np.linalg.norm(b)
print(f"  猫 vs 狗  cosine       = {cosine(a, b):.4f}")
print(f"  猫 vs 狗  归一化后点积 = {float(np.dot(an, bn)):.4f}  (应与上面几乎相同)")
print(f"  猫 vs Python 语言 cos = {cosine(doc_vecs[0], doc_vecs[3]):.4f}  (语义远，应明显更低)")
