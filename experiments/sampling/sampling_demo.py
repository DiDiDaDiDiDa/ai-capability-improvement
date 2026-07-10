"""
采样参数对比：同一个概率分布，看 temperature / top-k / top-p 如何改变挑词行为。
纯 numpy，不依赖任何模型/API。对应模块 01 · Day4 产出物。

运行: python3 sampling_demo.py
"""
import numpy as np

np.random.seed(42)
np.set_printoptions(precision=3, suppress=True)

# 候选下一个 token 及其 logits（原始分，未归一化）
vocab = ["好", "不错", "棒", "还行", "一般", "糟", "烂", "🤔"]
logits = np.array([3.0, 2.2, 1.8, 1.0, 0.3, -0.5, -1.2, -2.0])


def softmax(x):
    e = np.exp(x - x.max())
    return e / e.sum()


def show(title, probs):
    pairs = [f"{vocab[i]}:{probs[i]:.3f}" for i in range(len(vocab)) if probs[i] > 1e-4]
    print(f"  {title:<22} {'  '.join(pairs)}")


print("原始 logits ->", dict(zip(vocab, logits)), "\n")

# ---------- 1) Temperature：调分布形状 ----------
print("=== Temperature（调随机性/尖锐度）===")
for T in [0.3, 1.0, 2.0]:
    show(f"T={T}", softmax(logits / T))
print("  低T更尖(集中高分词/保守)，高T更平(长尾词也有机会/随机)\n")

# ---------- 2) Top-K：只保留前 K 个 ----------
def top_k(probs, k):
    idx = np.argsort(probs)[::-1][:k]      # 概率最高的 k 个下标
    out = np.zeros_like(probs)
    out[idx] = probs[idx]
    return out / out.sum()                  # 重新归一

print("=== Top-K（固定保留前 K 个，其余置 0）===")
base = softmax(logits)
for k in [2, 4]:
    show(f"top_k={k}", top_k(base, k))
print("  K 固定，不随分布形状变\n")

# ---------- 3) Top-P：累积到 P 的最小集合（动态数量）----------
def top_p(probs, p):
    order = np.argsort(probs)[::-1]         # 从高到低
    csum = np.cumsum(probs[order])
    cutoff = np.searchsorted(csum, p) + 1   # 累加到 >=p 的最小个数
    keep = order[:cutoff]
    out = np.zeros_like(probs)
    out[keep] = probs[keep]
    return out / out.sum(), cutoff

print("=== Top-P（累积到 P 的最小集合，数量自适应）===")
for p in [0.7, 0.9]:
    tp, n = top_p(base, p)
    show(f"top_p={p} (保留{n}个)", tp)
print("  P 越大保留越多；分布尖时留少、分布平时留多 -> 自适应\n")

# ---------- 4) 实际采样：同分布反复挑词，看差异 ----------
def sample(probs, n=12):
    return [vocab[np.random.choice(len(vocab), p=probs)] for _ in range(n)]

print("=== 同一分布反复采样 12 次，观察多样性 ===")
print("  贪心(永远最高)   :", ["好"] * 12)
print("  T=0.3 (保守)     :", sample(softmax(logits / 0.3)))
print("  T=1.0 (原始)     :", sample(softmax(logits)))
print("  T=2.0 (发散)     :", sample(softmax(logits / 2.0)))
print("  top_p=0.9        :", sample(top_p(base, 0.9)[0]))
print("\n  贪心永远'好'(呆板)；低T偶尔换词；高T/大top_p明显更花哨(也更易跑偏)。")
