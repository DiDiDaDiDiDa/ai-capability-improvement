"""
手写最小 BPE：训练 + 编码。纯标准库，帮助理解 BPE 到底在做什么。
对应模块 01 · Day1 产出物。
运行: python3 mini_bpe.py
"""
from collections import Counter


def get_pair_freqs(token_lists):
    """统计所有相邻符号对的出现频率。"""
    pairs = Counter()
    for toks in token_lists:
        for a, b in zip(toks, toks[1:]):
            pairs[(a, b)] += 1
    return pairs


def merge_pair(token_lists, pair):
    """把每个序列里的目标 pair 合并成一个新符号。"""
    a, b = pair
    merged = a + b
    out = []
    for toks in token_lists:
        new, i = [], 0
        while i < len(toks):
            if i < len(toks) - 1 and toks[i] == a and toks[i + 1] == b:
                new.append(merged)   # 命中相邻对 -> 合并
                i += 2
            else:
                new.append(toks[i])
                i += 1
        out.append(new)
    return out


def train_bpe(corpus, num_merges):
    """训练：反复合并出现频率最高的相邻对，返回合并规则（有序）。"""
    # 初始：每个词拆成字符列表，词尾加 '</w>' 标记单词边界
    token_lists = [list(word) + ["</w>"] for word in corpus]
    merges = []
    for step in range(num_merges):
        pairs = get_pair_freqs(token_lists)
        if not pairs:
            break
        best = max(pairs, key=pairs.get)      # 频率最高的相邻对
        if pairs[best] < 2:                    # 没有值得合并的了
            break
        token_lists = merge_pair(token_lists, best)
        merges.append(best)
        print(f"  merge #{step+1}: {best[0]!r}+{best[1]!r} -> {best[0]+best[1]!r}  (freq={pairs[best]})")
    return merges


def encode(word, merges):
    """编码：拿训练好的合并规则，按顺序对一个新词逐步合并。"""
    toks = list(word) + ["</w>"]
    for a, b in merges:              # 严格按训练时的合并顺序应用
        toks = merge_pair([toks], (a, b))[0]
    return toks


if __name__ == "__main__":
    # 极简语料：故意让 low/newest/widest 等共享子词，观察 BPE 如何"发现"它们
    corpus = (
        ["low"] * 5 + ["lower"] * 2 + ["newest"] * 6 + ["widest"] * 3
    )
    print("语料（词频）:", dict(Counter(corpus)))
    print("\n=== 训练：反复合并最高频相邻对 ===")
    merges = train_bpe(corpus, num_merges=10)

    print("\n=== 学到的合并规则（有序）===")
    print("  " + "  ".join(f"{a}+{b}" for a, b in merges))

    print("\n=== 用规则编码 ===")
    for w in ["newest", "widest", "lowest", "slowest"]:
        print(f"  {w:<9} -> {encode(w, merges)}")
    print("\n注意 'lowest'/'slowest' 训练时没出现过，但仍能用已学子词拼出来 —— 这就是 BPE 消灭 OOV 的方式。")
