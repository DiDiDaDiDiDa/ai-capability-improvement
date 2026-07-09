"""
用 tiktoken 直观感受 BPE 分词：同一句中英文切成几个 token、ID 是什么。
对应模块 01 · Day1 产出物。
运行: python3 demo_tiktoken.py
"""
import tiktoken

# GPT-4 / GPT-4o 系列用的编码器（字节级 BPE）
enc = tiktoken.get_encoding("cl100k_base")   # GPT-4 / 3.5
print(f"词表大小 (vocab size): {enc.n_vocab}\n")

samples = [
    "hello world",
    "tokenization",
    "unhappiness",
    "我爱学习AI",
    "自然语言处理很有意思",
    "ChatGPT emmm 🤔",
]

print(f"{'文本':<22}{'token数':>7}   tokens（切片）")
print("-" * 70)
for s in samples:
    ids = enc.encode(s)
    # 把每个 id 解回它对应的文本片段，直观看到“切在哪”
    pieces = [enc.decode([i]) for i in ids]
    print(f"{s:<22}{len(ids):>7}   {pieces}")

print("\n=== 细看一个中英混合例子的 ID ===")
s = "我爱AI"
ids = enc.encode(s)
for i in ids:
    print(f"  id={i:<8} -> {enc.decode([i])!r}")

print("\n=== 中英对比：谁更费 token ===")
en = "I love learning artificial intelligence"
zh = "我爱学习人工智能"
print(f"  英文 {en!r}: {len(enc.encode(en))} tokens")
print(f"  中文 {zh!r}: {len(enc.encode(zh))} tokens")
print("  （中文字符少，但字节级 BPE 下常更费 token —— 一个汉字通常 1~2 个 token）")
