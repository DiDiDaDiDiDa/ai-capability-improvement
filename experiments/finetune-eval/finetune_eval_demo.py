#!/usr/bin/env python3
"""
模块 05 · 微调与评估对照 Demo（纯标准库）。

五个抓手（对齐 docs/05-finetune-eval/README）：
  1) LoRA 参数量 + 前向：冻结 W，只训 B@A（低秩）
  2) QLoRA 概念：基座权重量化存储 + 仍用 LoRA 适配
  3) SFT / DPO / RLHF 流程定位（教学状态机，不真训）
  4) Prompt vs RAG vs FineTune 选型决策表（可断言）
  5) 评估：BLEU / ROUGE-L + LLM-as-Judge 位置偏差与交换缓解

运行: python3 finetune_eval_demo.py
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# 0) 工具
# ---------------------------------------------------------------------------


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    n, k, m = len(a), len(a[0]), len(b[0])
    assert k == len(b)
    out = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            s = 0.0
            for t in range(k):
                s += a[i][t] * b[t][j]
            out[i][j] = s
    return out


def mat_add(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[a[i][j] + b[i][j] for j in range(len(a[0]))] for i in range(len(a))]


def mat_scale(a: list[list[float]], s: float) -> list[list[float]]:
    return [[x * s for x in row] for row in a]


def vec_mat(v: list[float], w: list[list[float]]) -> list[float]:
    """y = x @ W，x:(d_in,), W:(d_in, d_out) stored as rows of d_in."""
    d_in, d_out = len(w), len(w[0])
    assert len(v) == d_in
    out = [0.0] * d_out
    for j in range(d_out):
        s = 0.0
        for i in range(d_in):
            s += v[i] * w[i][j]
        out[j] = s
    return out


# ---------------------------------------------------------------------------
# 1) LoRA：参数量 + 前向
# ---------------------------------------------------------------------------


@dataclass
class LoRALinear:
    """
    y = x @ W + scale * x @ A.T @ B.T   （实现上用 A:(r,d_in), B:(d_out,r) 的等价形式）
    教学简化：W frozen (d_in x d_out), A (d_in x r), B (r x d_out),
    ΔW = A @ B，y = x @ (W + scale * A@B)
    """

    d_in: int
    d_out: int
    r: int
    alpha: float
    W: list[list[float]]
    A: list[list[float]]
    B: list[list[float]]

    @property
    def scale(self) -> float:
        return self.alpha / self.r

    def forward(self, x: list[float]) -> list[float]:
        base = vec_mat(x, self.W)
        # x @ A -> (r,); then @ B -> (d_out,)
        xa = [0.0] * self.r
        for k in range(self.r):
            s = 0.0
            for i in range(self.d_in):
                s += x[i] * self.A[i][k]
            xa[k] = s
        delta = [0.0] * self.d_out
        for j in range(self.d_out):
            s = 0.0
            for k in range(self.r):
                s += xa[k] * self.B[k][j]
            delta[j] = self.scale * s
        return [base[j] + delta[j] for j in range(self.d_out)]

    def trainable_params(self) -> int:
        return self.d_in * self.r + self.r * self.d_out

    def frozen_params(self) -> int:
        return self.d_in * self.d_out


def make_lora(d_in: int, d_out: int, r: int, alpha: float, seed: int = 0) -> LoRALinear:
    rng = random.Random(seed)
    # W ~ small random (frozen base)
    W = [[rng.uniform(-0.1, 0.1) for _ in range(d_out)] for _ in range(d_in)]
    # LoRA init: A random, B zero → ΔW=0 at start (common practice)
    A = [[rng.gauss(0, 0.02) for _ in range(r)] for _ in range(d_in)]
    B = [[0.0 for _ in range(d_out)] for _ in range(r)]
    return LoRALinear(d_in, d_out, r, alpha, W, A, B)


def demo_lora() -> dict[str, Any]:
    section("1) LoRA：参数量 + 前向（冻结 W，只训 A/B）")
    d_in, d_out, r, alpha = 512, 512, 8, 16.0
    layer = make_lora(d_in, d_out, r, alpha, seed=42)
    full = d_in * d_out
    lora_n = layer.trainable_params()
    ratio = lora_n / full
    print(f"  full W params     = {full}")
    print(f"  LoRA trainable    = {lora_n}  (d*r + r*d = 2*d*r when square)")
    print(f"  trainable ratio   = {ratio:.4%}")
    print(f"  scale = alpha/r   = {layer.scale}")

    assert_true(lora_n == 2 * d_in * r, "square LoRA params = 2*d*r")
    assert_true(ratio < 0.05, "LoRA should be << full FT params")
    assert_true(layer.frozen_params() == full, "W frozen count")

    # B=0 → forward == base only
    x = [0.01 * (i % 7) for i in range(d_in)]
    y0 = layer.forward(x)
    y_base = vec_mat(x, layer.W)
    max_diff0 = max(abs(a - b) for a, b in zip(y0, y_base))
    print(f"  init B=0 |y - xW|_∞ = {max_diff0:.2e} (expect ~0)")
    assert_true(max_diff0 < 1e-9, "LoRA init should be identity-ish (Δ=0)")

    # after "training" B a bit, output moves
    for j in range(d_out):
        layer.B[0][j] = 0.05
    y1 = layer.forward(x)
    moved = math.sqrt(sum((a - b) ** 2 for a, b in zip(y1, y0)))
    print(f"  after ΔB  ||y1-y0||_2 = {moved:.4f} (expect > 0)")
    assert_true(moved > 1e-3, "updating B must change output")

    # rank bottleneck: ΔW = A@B has rank ≤ r
    # check: columns of ΔW live in span of A columns — numerical rank via
    # ΔW = A @ B, so rank(ΔW) ≤ min(r, ...)
    dW = mat_mul(layer.A, layer.B)  # (d_in x d_out)
    # crude rank: number of non-near-zero singular values via Gram on first r+2 cols
    # simpler assert: dW == A@B structure already; param formula is the interview point
    print(f"  ΔW shape = {len(dW)}x{len(dW[0])}, rank ≤ r={r}")
    assert_true(layer.scale == alpha / r, "scale = alpha/r")

    return {
        "full_params": full,
        "lora_params": lora_n,
        "ratio": ratio,
        "r": r,
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# 2) QLoRA 概念：量化基座 + LoRA
# ---------------------------------------------------------------------------


def quantize_int8_symmetric(W: list[list[float]]) -> tuple[list[list[int]], list[float]]:
    """
    按列对称量化到 int8：q = round(w / scale), scale = max|w|/127。
    返回 (Q, scales_per_col)。
    """
    d_in, d_out = len(W), len(W[0])
    scales = []
    Q = [[0 for _ in range(d_out)] for _ in range(d_in)]
    for j in range(d_out):
        mx = max(abs(W[i][j]) for i in range(d_in)) or 1e-8
        s = mx / 127.0
        scales.append(s)
        for i in range(d_in):
            Q[i][j] = int(max(-127, min(127, round(W[i][j] / s))))
    return Q, scales


def dequant_int8(Q: list[list[int]], scales: list[float]) -> list[list[float]]:
    d_in, d_out = len(Q), len(Q[0])
    return [[Q[i][j] * scales[j] for j in range(d_out)] for i in range(d_in)]


def demo_qlora() -> dict[str, Any]:
    section("2) QLoRA 概念：INT8 存基座 + LoRA 适配（仍训小矩阵）")
    d_in, d_out, r = 64, 64, 4
    layer = make_lora(d_in, d_out, r, alpha=8.0, seed=7)
    Q, scales = quantize_int8_symmetric(layer.W)
    W_hat = dequant_int8(Q, scales)

    # 显存教学账：FP16 基座 vs INT8 基座 + FP16 LoRA
    bytes_fp16_full = d_in * d_out * 2
    bytes_int8_base = d_in * d_out * 1
    bytes_lora_fp16 = (d_in * r + r * d_out) * 2
    qlora_store = bytes_int8_base + bytes_lora_fp16
    print(f"  FP16 full store   ≈ {bytes_fp16_full} B")
    print(f"  INT8 base + LoRA  ≈ {qlora_store} B  (base {bytes_int8_base} + lora {bytes_lora_fp16})")
    assert_true(qlora_store < bytes_fp16_full, "QLoRA storage should beat FP16 full")

    # 量化误差有限
    err = 0.0
    n = 0
    for i in range(d_in):
        for j in range(d_out):
            err += (layer.W[i][j] - W_hat[i][j]) ** 2
            n += 1
    rmse = math.sqrt(err / n)
    print(f"  quant RMSE        = {rmse:.6f}")
    assert_true(rmse < 0.05, "toy INT8 RMSE should be small on small weights")

    # QLoRA 前向：用 W_hat（量化恢复）+ 可训 LoRA
    layer.W = W_hat
    for j in range(d_out):
        layer.B[0][j] = 0.1
    x = [0.02] * d_in
    y = layer.forward(x)
    assert_true(len(y) == d_out and any(abs(v) > 0 for v in y), "qlora forward runs")
    print("  QLoRA forward: OK (frozen dequant W + trainable A/B)")
    print("  面试点: QLoRA = 量化压缩基座显存 + LoRA 仍 FP16/BF16 训练小适配器")
    return {
        "bytes_fp16_full": bytes_fp16_full,
        "bytes_qlora": qlora_store,
        "rmse": rmse,
    }


# ---------------------------------------------------------------------------
# 3) SFT / DPO / RLHF 定位
# ---------------------------------------------------------------------------


@dataclass
class PrefPair:
    prompt: str
    chosen: str
    rejected: str


def sft_loss_proxy(pred_tokens: list[str], gold_tokens: list[str]) -> float:
    """教学：1 - token 准确率，模拟 CE 监督。"""
    if not gold_tokens:
        return 1.0
    n = min(len(pred_tokens), len(gold_tokens))
    hit = sum(1 for i in range(n) if pred_tokens[i] == gold_tokens[i])
    # 长度差惩罚
    hit -= abs(len(pred_tokens) - len(gold_tokens)) * 0.1
    return max(0.0, 1.0 - hit / len(gold_tokens))


def dpo_pref_score(chosen_logp: float, rejected_logp: float, beta: float = 0.1) -> float:
    """
    教学版 DPO 信号：σ(β * (logπ_c - logπ_r)) 越大越好。
    不引入 ref model，只演示「成对偏好」而非「模仿单条 gold」。
    """
    return 1.0 / (1.0 + math.exp(-beta * (chosen_logp - rejected_logp)))


def demo_alignment_pipeline() -> dict[str, Any]:
    section("3) SFT → DPO / RLHF：流程定位（不真训）")
    # SFT：模仿单条标准答案
    gold = "根据资料，一线城市住宿标准为每晚 500 元。".split()
    pred_good = "根据资料，一线城市住宿标准为每晚 500 元。".split()
    pred_bad = "我觉得大概三四百吧随便住。".split()
    loss_g = sft_loss_proxy(pred_good, gold)
    loss_b = sft_loss_proxy(pred_bad, gold)
    print(f"  SFT proxy loss good={loss_g:.3f} bad={loss_b:.3f}")
    assert_true(loss_g < loss_b, "SFT: closer to gold → lower loss")

    # DPO：chosen/rejected 成对
    pair = PrefPair(
        prompt="住宿标准？",
        chosen="一线城市每晚不超过 500 元。",
        rejected="没有标准想住哪住哪。",
    )
    # 假装策略 logp：好回答更高
    s_pos = dpo_pref_score(chosen_logp=-1.2, rejected_logp=-3.5)
    s_neg = dpo_pref_score(chosen_logp=-3.5, rejected_logp=-1.2)  # 反了
    print(f"  DPO pref score correct_order={s_pos:.3f} reversed={s_neg:.3f}")
    assert_true(s_pos > 0.5 > s_neg, "DPO prefers higher logp on chosen")

    pipeline = [
        ("SFT", "单条 (x,y*) 模仿，学格式/任务"),
        ("RM/RLHF", "训练奖励模型 + RL 优化策略（重、不稳）"),
        ("DPO", "直接用偏好对 (chosen,rejected) 更新策略，省 RM+RL"),
    ]
    for name, desc in pipeline:
        print(f"  - {name}: {desc}")

    assert_true(pipeline[0][0] == "SFT" and pipeline[2][0] == "DPO", "order")
    return {"sft_loss_good": loss_g, "dpo_score": s_pos}


# ---------------------------------------------------------------------------
# 4) Prompt / RAG / FineTune 选型
# ---------------------------------------------------------------------------


def choose_stack(need: dict[str, Any]) -> str:
    """
    规则引擎版选型（面试可讲清 if-else）：
      - 要新知识/可溯源/常更新 → RAG
      - 要改风格/格式/领域话术且稳定 → FineTune（常叠 RAG）
      - 只要行为/格式轻改 → Prompt
    """
    if need.get("knowledge_external") or need.get("must_cite") or need.get("updates_weekly"):
        if need.get("style_lock") and need.get("volume_high"):
            return "RAG+FineTune"
        return "RAG"
    if need.get("style_lock") or need.get("domain_format_strict"):
        return "FineTune"
    if need.get("behavior_tweak") or need.get("format_only"):
        return "Prompt"
    return "Prompt"


def demo_routing() -> None:
    section("4) Prompt vs RAG vs FineTune 选型决策")
    cases = [
        ({"format_only": True}, "Prompt", "JSON 输出格式"),
        ({"knowledge_external": True, "must_cite": True, "updates_weekly": True}, "RAG", "企业制度问答"),
        ({"style_lock": True, "domain_format_strict": True}, "FineTune", "客服固定话术语气"),
        (
            {
                "knowledge_external": True,
                "must_cite": True,
                "style_lock": True,
                "volume_high": True,
            },
            "RAG+FineTune",
            "高量客服：知识用 RAG，口吻用 FT",
        ),
        ({"behavior_tweak": True}, "Prompt", "更简短的回答"),
    ]
    for need, expect, title in cases:
        got = choose_stack(need)
        print(f"  [{title}] need={need} → {got}")
        assert_true(got == expect, f"{title}: expect {expect}, got {got}")

    # 不该微调
    dont = choose_stack({"knowledge_external": True, "updates_weekly": True})
    assert_true(dont == "RAG", "频繁更新知识不该靠 FT 塞进权重")
    print("  不该 FT: 知识周更 → RAG（权重里烤知识 = 过期即事故）")


# ---------------------------------------------------------------------------
# 5) BLEU / ROUGE-L
# ---------------------------------------------------------------------------


def _tokens(s: str) -> list[str]:
    s = s.lower().strip()
    # 中英混：字级 + 英文词
    en = re.findall(r"[a-z0-9]+", s)
    zh = re.findall(r"[一-鿿]", s)
    return en + zh if (en or zh) else s.split()


def ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def bleu(candidate: str, reference: str, max_n: int = 4) -> float:
    """
    简化 corpus-free BLEU：均匀权重的 modified precision + brevity penalty。
    """
    c = _tokens(candidate)
    r = _tokens(reference)
    if not c or not r:
        return 0.0
    precisions = []
    for n in range(1, max_n + 1):
        cn = ngrams(c, n)
        rn = ngrams(r, n)
        if not cn:
            precisions.append(0.0)
            continue
        from collections import Counter

        rc = Counter(rn)
        cc = Counter(cn)
        overlap = sum(min(cc[g], rc[g]) for g in cc)
        precisions.append(overlap / len(cn))
    # 避免 log(0)
    if any(p == 0 for p in precisions):
        # 平滑
        precisions = [p if p > 0 else 1e-9 for p in precisions]
    log_avg = sum(math.log(p) for p in precisions) / max_n
    bp = 1.0 if len(c) > len(r) else math.exp(1 - len(r) / len(c))
    return bp * math.exp(log_avg)


def lcs_len(a: list[str], b: list[str]) -> int:
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]


def rouge_l(candidate: str, reference: str) -> float:
    c, r = _tokens(candidate), _tokens(reference)
    if not c or not r:
        return 0.0
    lcs = lcs_len(c, r)
    prec = lcs / len(c)
    rec = lcs / len(r)
    if prec + rec == 0:
        return 0.0
    beta2 = 1.2**2  # 略偏 recall，贴近常见 rouge-l
    return (1 + beta2) * prec * rec / (rec + beta2 * prec)


def demo_metrics() -> dict[str, float]:
    section("5a) BLEU / ROUGE-L")
    ref = "一线城市差旅住宿标准为每晚不超过 500 元"
    good = "一线城市住宿标准每晚不超过 500 元"
    bad = "今天天气不错适合出去玩"
    paraphrase = "根据制度，一线城市每晚住宿费上限是 500 元"

    b_good, b_bad = bleu(good, ref), bleu(bad, ref)
    r_good, r_bad = rouge_l(good, ref), rouge_l(bad, ref)
    b_para, r_para = bleu(paraphrase, ref), rouge_l(paraphrase, ref)

    print(f"  BLEU  good={b_good:.3f}  bad={b_bad:.3f}  paraphrase={b_para:.3f}")
    print(f"  ROUGE good={r_good:.3f}  bad={r_bad:.3f}  paraphrase={r_para:.3f}")
    assert_true(b_good > b_bad and r_good > r_bad, "metrics rank good > bad")
    # 释义：字面指标可能偏低（BLEU 苛刻）——这是局限
    print("  局限: 释义正确但用词不同 → BLEU 可能偏低（表面重合驱动）")
    return {"bleu_good": b_good, "rouge_good": r_good, "bleu_para": b_para}


# ---------------------------------------------------------------------------
# 6) LLM-as-Judge + 位置偏差
# ---------------------------------------------------------------------------


def mock_judge(question: str, ans_a: str, ans_b: str, prefer_first: float = 0.0) -> str:
    """
    教学 Judge：
      - 基础分：与 question 的 token 重叠 + 是否含关键数字 500
      - prefer_first>0 时模拟位置偏差：无脑抬 A
    返回 'A' | 'B' | 'TIE'
    """
    q_tok = set(_tokens(question))

    def score(ans: str) -> float:
        t = set(_tokens(ans))
        ov = len(q_tok & t)
        bonus = 2.0 if "500" in ans else 0.0
        penalty = -3.0 if any(x in ans for x in ("不知道", "瞎猜", "随便")) else 0.0
        return ov + bonus + penalty + 0.01 * len(ans)

    sa, sb = score(ans_a), score(ans_b)
    sa += prefer_first  # 位置偏差：总给先出现的加分
    if abs(sa - sb) < 0.5:
        return "TIE"
    return "A" if sa > sb else "B"


def demo_judge() -> None:
    section("5b) LLM-as-Judge：位置偏差与交换缓解")
    q = "一线城市差旅住宿标准是多少？"
    correct = "一线城市每晚不超过 500 元。"
    wrong = "没有标准，随便住，不知道。"

    # 无偏差：应选 correct
    j1 = mock_judge(q, correct, wrong, prefer_first=0.0)
    j2 = mock_judge(q, wrong, correct, prefer_first=0.0)
    print(f"  unbiased: A=correct → {j1}; A=wrong → {j2}")
    assert_true(j1 == "A" and j2 == "B", "unbiased judge picks correct")

    # 强位置偏差：错误答案放 A 也能赢
    biased = mock_judge(q, wrong, correct, prefer_first=10.0)
    print(f"  biased prefer_first=10, A=wrong → {biased} (expect A 被抬赢)")
    assert_true(biased == "A", "position bias can crown wrong answer")

    # 缓解：交换顺序投两票，不一致则标可疑 / 取内容分
    def judge_with_swap(ans1: str, ans2: str) -> str:
        v1 = mock_judge(q, ans1, ans2, prefer_first=10.0)  # 仍带偏差
        v2 = mock_judge(q, ans2, ans1, prefer_first=10.0)
        # v1==A means prefer ans1; v2==A means prefer ans2 (because swapped)
        vote_ans1 = 0
        vote_ans2 = 0
        if v1 == "A":
            vote_ans1 += 1
        elif v1 == "B":
            vote_ans2 += 1
        if v2 == "A":
            vote_ans2 += 1
        elif v2 == "B":
            vote_ans1 += 1
        if vote_ans1 > vote_ans2:
            return "ans1"
        if vote_ans2 > vote_ans1:
            return "ans2"
        # 平票：回退无偏内容分
        return "ans1" if mock_judge(q, ans1, ans2, 0.0) == "A" else "ans2"

    mitigated = judge_with_swap(wrong, correct)
    print(f"  swap mitigation: ans1=wrong ans2=correct → {mitigated}")
    assert_true(mitigated == "ans2", "swap voting should recover correct")

    print("  其他偏差: 长度偏好、自我偏好、顺序；缓解=交换/多 judge/校准提示/盲评")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    print("Module 05 · Finetune & Eval demo (stdlib)")
    lora = demo_lora()
    qlora = demo_qlora()
    align = demo_alignment_pipeline()
    demo_routing()
    metrics = demo_metrics()
    demo_judge()

    section("DONE · Module 05 finetune-eval green")
    print(
        f"  LoRA ratio={lora['ratio']:.2%} | QLoRA store {qlora['bytes_qlora']}<{qlora['bytes_fp16_full']} | "
        f"BLEU_good={metrics['bleu_good']:.2f} | DPO={align['dpo_score']:.2f}"
    )
    print("EXIT:0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
