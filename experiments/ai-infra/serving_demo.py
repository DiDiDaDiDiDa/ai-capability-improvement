#!/usr/bin/env python3
"""模块 06 · AI Infra / Serving 教学 demo（纯标准库，不依赖 torch/numpy）。

目标：用最小可运行代码把 vLLM 的四个核心机制讲透，跑通即 EXIT 0。
  1) KV Cache        —— 自回归为什么必须缓存，省了多少重复算
  2) Continuous Batching —— 相比静态 batching 为什么吞吐高
  3) PagedAttention  —— KV 显存分页，消灭内部碎片
  4) Speculative Decoding —— 小模型草稿 + 大模型并行验证

每个机制都用「断言 + 数字」证明结论，不空谈。
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

random.seed(42)
SEP = "=" * 60


def section(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


# ============================================================
# 1) KV Cache：自回归解码的重复计算账
# ============================================================
def attention_flops(seq_len: int, d: int) -> int:
    """单步注意力的粗略乘加次数：Q·K^T (seq*d) + 权重·V (seq*d)。"""
    return 2 * seq_len * d


def decode_cost(n_new: int, prompt_len: int, d: int, use_cache: bool) -> int:
    """生成 n_new 个 token 的总注意力成本。

    无缓存：第 t 步要对前面所有 token 重算 K/V → 成本随 t 线性增长。
    有缓存：K/V 存下来，第 t 步只算「新 token 对全序列」一次。
    """
    total = 0
    for t in range(n_new):
        cur_len = prompt_len + t + 1
        if use_cache:
            total += attention_flops(cur_len, d)          # 只算新 query
        else:
            total += attention_flops(cur_len, d) * cur_len  # 全序列重算
    return total


def demo_kv_cache() -> None:
    section("1) KV Cache：省掉重复计算的自回归缓存")
    prompt_len, n_new, d = 128, 64, 512
    no_cache = decode_cost(n_new, prompt_len, d, use_cache=False)
    cached = decode_cost(n_new, prompt_len, d, use_cache=True)
    speedup = no_cache / cached
    print(f"  prompt={prompt_len} 生成={n_new} d={d}")
    print(f"  无缓存总成本  = {no_cache:,}")
    print(f"  有缓存总成本  = {cached:,}")
    print(f"  加速比        = {speedup:.1f}x（缓存把每步的全序列重算降为单 query）")
    print(f"  代价: KV 显存 = 2 * layers * heads * head_dim * seq * batch（换来的省算）")
    assert cached < no_cache, "缓存必须更省"
    assert speedup > 10, "长序列下加速应显著"
    print("  ✅ KV Cache: 用显存换算力，是 batching/paging 的前提")


# ============================================================
# 2) Continuous Batching：静态 batch 的空转 vs 动态填充
# ============================================================
@dataclass
class Req:
    rid: int
    out_len: int          # 该请求需要生成多少 token
    done_at: int = -1     # 完成于第几步


def static_batching(reqs: list[Req], batch: int) -> tuple[int, float]:
    """静态：一批凑齐 batch 个，必须等批内最长的那个跑完才能换下一批。"""
    steps = 0
    busy = 0            # 有效计算 slot 数
    for i in range(0, len(reqs), batch):
        group = reqs[i:i + batch]
        span = max(r.out_len for r in group)   # 批内最长决定整批时长
        steps += span
        busy += sum(r.out_len for r in group)  # 短请求跑完后 slot 空转
    util = busy / (steps * batch)
    return steps, util


def continuous_batching(reqs: list[Req], batch: int) -> tuple[int, float]:
    """连续：每一步检查谁完成了，立刻把等待队列里的新请求填进空出的 slot。"""
    waiting = list(reqs)
    running: list[int] = []       # 每个 slot 上请求的剩余步数
    steps = 0
    busy = 0
    while waiting or running:
        # 有空 slot 就从等待队列补满（这是 continuous batching 的关键动作）
        while len(running) < batch and waiting:
            running.append(waiting.pop(0).out_len)
        steps += 1
        busy += len(running)                      # 本步真正在算的 slot
        running = [r - 1 for r in running]
        running = [r for r in running if r > 0]   # 完成的立即退出，腾 slot
    util = busy / (steps * batch)
    return steps, util


def demo_continuous_batching() -> None:
    section("2) Continuous Batching：动态填充空 slot 提吞吐")
    # 构造长度差异大的请求负载（真实场景就是长短不一）
    reqs = [Req(i, random.choice([4, 8, 16, 64, 128])) for i in range(64)]
    batch = 8
    s_steps, s_util = static_batching(reqs, batch)
    c_steps, c_util = continuous_batching(reqs, batch)
    print(f"  负载: {len(reqs)} 个请求，输出长度 4~128 不等，batch={batch}")
    print(f"  静态 batching : {s_steps} 步, GPU 利用率 {s_util:.1%}")
    print(f"  连续 batching : {c_steps} 步, GPU 利用率 {c_util:.1%}")
    print(f"  吞吐提升      = {s_steps / c_steps:.2f}x（步数越少，单位时间出的 token 越多）")
    assert c_steps < s_steps, "连续 batching 步数必须更少"
    assert c_util > s_util, "连续 batching 利用率必须更高"
    print("  ✅ 静态 batch 被最长请求拖死；连续 batch 谁完成谁退出、立刻补新请求")


# ============================================================
# 3) PagedAttention：KV Cache 分页，消灭内部碎片
# ============================================================
class PagedKVCache:
    """把 KV 显存切成固定大小的块（page），像 OS 虚拟内存一样按需分配。

    朴素方案：给每个请求按 max_len 连续预留 → 短请求浪费一大截（内部碎片）。
    分页方案：只在实际生成时按块分配，块表(block_table)记录逻辑→物理映射。
    """
    def __init__(self, total_blocks: int, block_size: int):
        self.block_size = block_size
        self.free = list(range(total_blocks))        # 空闲物理块池
        self.block_table: dict[int, list[int]] = {}  # rid -> 物理块列表
        self.filled: dict[int, int] = {}             # rid -> 已用 token 数

    def append(self, rid: int, n_tokens: int) -> None:
        """为请求追加 n_tokens 个 token 的 KV，容量不够就再要一个物理块。"""
        table = self.block_table.setdefault(rid, [])
        need_total = self.filled.get(rid, 0) + n_tokens
        while len(table) * self.block_size < need_total:
            if not self.free:
                raise MemoryError("KV 块耗尽——真实 vLLM 触发 preemption/swap")
            table.append(self.free.pop(0))           # 按需分配，非连续也 OK
        self.filled[rid] = need_total

    def free_req(self, rid: int) -> None:
        """请求结束，物理块立即归还池子（连续 batching 才能复用）。"""
        for blk in self.block_table.pop(rid, []):
            self.free.append(blk)
        self.filled.pop(rid, None)

    def used_blocks(self) -> int:
        return sum(len(t) for t in self.block_table.values())


def demo_paged_attention() -> None:
    section("3) PagedAttention：KV 分页，把内部碎片降到 < 1 块")
    block_size, max_len = 16, 512
    # 真实长度长短不一；朴素方案却要按 max_len 预留
    lengths = {i: random.choice([10, 30, 200, 500]) for i in range(8)}
    naive_slots = len(lengths) * max_len                       # 每请求预留 max_len
    naive_used = sum(lengths.values())
    naive_waste = naive_slots - naive_used

    cache = PagedKVCache(total_blocks=10_000, block_size=block_size)
    for rid, ln in lengths.items():
        cache.append(rid, ln)                                  # 按实际长度分页
    paged_slots = cache.used_blocks() * block_size
    paged_waste = paged_slots - naive_used                     # 仅每请求最后一块的零头

    print(f"  block_size={block_size} max_len={max_len} 请求真实长度={list(lengths.values())}")
    print(f"  朴素连续预留 : 占 {naive_slots} slot, 浪费 {naive_waste} ({naive_waste/naive_slots:.0%})")
    print(f"  分页按需分配 : 占 {paged_slots} slot, 浪费 {paged_waste} ({paged_waste/paged_slots:.0%})")
    print(f"  显存节省      = {(1 - paged_slots/naive_slots):.0%}（同显存能塞更多并发请求）")
    # 分页碎片上界：每个请求最多浪费不足一个 block
    assert paged_waste < len(lengths) * block_size, "分页碎片必须 < 请求数 * block_size"
    assert paged_slots < naive_slots, "分页必须比朴素预留省"
    print("  ✅ 类比 OS 虚拟内存：逻辑连续、物理分页；块表做映射，碎片仅剩每请求最后一块零头")


# ============================================================
# 4) Speculative Decoding：小模型草稿 + 大模型并行验证
# ============================================================
def speculative_decode(target_tokens: list[int], k: int, accept_p: float) -> dict:
    """草稿模型一次猜 k 个 token，大模型并行验证，从首个不匹配处截断。

    - 每轮：draft 出 k 个候选；target 一次前向验证，接受连续匹配的前缀 + 补 1 个纠正
    - 大模型前向次数 = 轮数（关键：验证 k 个只需 1 次前向，不是 k 次）
    """
    n = len(target_tokens)
    produced = 0
    target_forwards = 0
    draft_forwards = 0
    while produced < n:
        target_forwards += 1                     # 每轮大模型只前向一次
        accepted = 0
        for _ in range(k):
            if produced + accepted >= n:
                break
            draft_forwards += 1
            if random.random() < accept_p:       # 草稿命中 → 接受
                accepted += 1
            else:
                break                            # 首次不匹配即停
        # 接受 accepted 个 + 大模型这一步顺带产出 1 个纠正 token
        produced += accepted + 1
    produced = min(produced, n)
    baseline_forwards = n                        # 逐 token 解码：n 次大模型前向
    speedup = baseline_forwards / target_forwards
    return {"target_forwards": target_forwards, "draft_forwards": draft_forwards,
            "baseline": baseline_forwards, "speedup": speedup}


def demo_speculative() -> None:
    section("4) Speculative Decoding：小模型草稿 + 大模型一次验证")
    seq = list(range(200))                       # 目标要生成 200 个 token
    k = 4
    results = {}                                 # 存下来复用，避免重复调用导致数字漂移
    for accept_p in (0.9, 0.5):
        r = speculative_decode(seq, k=k, accept_p=accept_p)
        results[accept_p] = r
        print(f"  接受率 p={accept_p} k={k}:")
        print(f"    逐 token 大模型前向 = {r['baseline']}")
        print(f"    投机后大模型前向    = {r['target_forwards']}  加速 {r['speedup']:.2f}x")
    high, low = results[0.9], results[0.5]
    print(f"  结论: 草稿命中率越高，加速越大（{high['speedup']:.2f}x > {low['speedup']:.2f}x）")
    assert high["target_forwards"] < high["baseline"], "投机必须减少大模型前向"
    assert high["speedup"] > low["speedup"], "命中率高 → 加速大"
    print("  ✅ 结果分布不变（大模型验证保证正确性）；命中率低时反而可能亏（草稿白算）")


def main() -> None:
    print("Module 06 · AI Infra / Serving demo (stdlib)")
    demo_kv_cache()
    demo_continuous_batching()
    demo_paged_attention()
    demo_speculative()
    section("DONE · Module 06 serving green")
    print("  KV Cache 省重复算 | Continuous Batching 提利用率 |")
    print("  PagedAttention 消碎片 | Speculative Decoding 减大模型前向")
    print("EXIT:0")


if __name__ == "__main__":
    main()
