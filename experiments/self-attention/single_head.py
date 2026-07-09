"""
手写单头 Self-Attention：把公式 softmax(QKᵀ/√dₖ)·V 逐步跑出真实数值。
对应模块 01 · Day3 产出物。

运行: python3 single_head.py
"""
import numpy as np

np.random.seed(0)
np.set_printoptions(precision=3, suppress=True)

# ---------- 输入：4 个 token，每个是 8 维向量（Day2 的 embedding 就是这种向量）----------
n_tokens, d_model = 4, 8
tokens = ["猫", "累", "它", "睡"]
X = np.random.randn(n_tokens, d_model)      # [4, 8]  每行一个词向量
print(f"输入 X: {n_tokens} 个 token，每个 {d_model} 维\n")

# ---------- 三个投影矩阵 Wq/Wk/Wv：把词向量投影成 Q/K/V ----------
d_k = 8                                      # Q/K/V 的维度
Wq = np.random.randn(d_model, d_k)
Wk = np.random.randn(d_model, d_k)
Wv = np.random.randn(d_model, d_k)

Q = X @ Wq        # [4, 8]  “我想找什么”
K = X @ Wk        # [4, 8]  “我是什么标签”
V = X @ Wv        # [4, 8]  “我的实际内容”


def softmax(x, axis=-1):
    x = x - x.max(axis=axis, keepdims=True)  # 减最大值防溢出
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


# ---------- 公式四步 ----------
# ① QKᵀ：每个词的 Q 和所有词的 K 点积 -> 相关度分数矩阵 [4,4]
scores = Q @ K.T
print("① QKᵀ 原始分数矩阵 (第i行=词i对各词的关注原始分):")
print(scores, "\n")

# ② ÷√dₖ：缩放，防止高维点积过大把 softmax 推入饱和区
scaled = scores / np.sqrt(d_k)
print(f"② 缩放后 (÷√{d_k}={np.sqrt(d_k):.3f})：数值收敛，softmax 更平滑\n")

# ③ softmax：每行归一成“加起来=1”的注意力权重
weights = softmax(scaled, axis=-1)
print("③ softmax 后的注意力权重 (每行和=1):")
for i, t in enumerate(tokens):
    row = "  ".join(f"{tokens[j]}:{weights[i,j]:.2f}" for j in range(n_tokens))
    print(f"   {t} 关注 -> {row}")
print(f"   各行之和: {weights.sum(axis=1)}\n")

# ④ ×V：按权重加权所有词的 V -> 每个词吸收上下文后的新向量
out = weights @ V
print(f"④ 输出 [4,8]：每个词融合上下文后的新表示（形状与输入一致，可堆叠下一层）")
print(out, "\n")

# ---------- 对比实验：不缩放会怎样（看 √dₖ 的作用）----------
print("=== 对比：不除以 √dₖ，softmax 会更“尖锐”(趋近 one-hot) ===")
w_noscale = softmax(scores, axis=-1)
print(f"  缩放后 词'{tokens[0]}'的权重分布 : {weights[0]}")
print(f"  不缩放 词'{tokens[0]}'的权重分布 : {w_noscale[0]}")
print("  不缩放时最大权重更高、其余更低 -> 分布更尖 -> 梯度更易消失，这就是要缩放的原因。")
