"""
推理增强模式对比：CoT / Self-Consistency / ToT / ReAct / Reflection。
纯 Python 标准库，不依赖模型/API。对应模块 02 · Day6。

运行: python3 reasoning_patterns.py

设计目标：
- 把五种模式落成「可解析的 messages / 模拟轨迹」
- 同一业务题对比结构差异、循环步数、代价量级
- 让读者看清机制本身，而不是调某个模型的玄学参数
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# 共用题面：需要「政策 + 物流」才能答对 → 逼出工具/多步推理
# ---------------------------------------------------------------------------

QUESTION = (
    "用户说：订单 8821 的耳机到货就坏了，想退货。问能不能退、物流到哪了？"
)

REFUND_POLICY = {
    "electronics": "签收 7 天内质量问题可退，需提供开箱视频。",
    "window_days": 7,
}

LOGISTICS = {
    "8821": {"status": "已签收", "signed_at": "2026-07-12", "item": "耳机"},
}


# ---------------------------------------------------------------------------
# 1) CoT：只改 system 协议，消息条数几乎不变
# ---------------------------------------------------------------------------


def build_direct_messages(question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "你是电商客服。直接回答用户，简洁。",
        },
        {"role": "user", "content": question},
    ]


def build_cot_messages(question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是电商客服。先逐步推理（政策、订单状态、结论），"
                "最后一行输出：答案: <一句话结论>。"
            ),
        },
        {"role": "user", "content": question},
    ]


# ---------------------------------------------------------------------------
# 2) Self-Consistency：N 条独立 CoT 轨迹 → 抽答案 → 投票
# ---------------------------------------------------------------------------


@dataclass
class SCTrace:
    """一条伪 CoT 轨迹（真实场景里来自 temperature>0 的多次 API 调用）。"""

    reasoning: str
    answer: str


def extract_answer(text: str) -> str:
    """从 '答案: xxx' 或整段文本里抽出最终答案键。"""
    m = re.search(r"答案\s*[:：]\s*(.+)", text)
    if m:
        return m.group(1).strip()
    return text.strip()


def self_consistency_vote(traces: list[SCTrace]) -> dict[str, Any]:
    answers = [extract_answer(t.answer) for t in traces]
    counter = Counter(answers)
    winner, votes = counter.most_common(1)[0]
    return {
        "winner": winner,
        "votes": votes,
        "n": len(traces),
        "tally": dict(counter),
        "cost_factor": len(traces),  # 约 ×N 费用
    }


def demo_self_consistency() -> dict[str, Any]:
    # 固定 5 条"采样结果"：模拟不同路径，正确结论应占多数
    traces = [
        SCTrace(
            "步骤1: 订单已签收。步骤2: 电子产品 7 天质量问题可退。",
            "答案: 可退（质量问题，在 7 天内）",
        ),
        SCTrace(
            "先看物流：已签收。再看政策：7 天可退。",
            "答案: 可退（质量问题，在 7 天内）",
        ),
        SCTrace(
            "没查政策，凭感觉：坏了就能退。",
            "答案: 可退（质量问题，在 7 天内）",
        ),
        SCTrace(
            "只记得食品不能退，耳机可能不行。",
            "答案: 不可退",
        ),
        SCTrace(
            "签收超过 15 天了吧？（算错日期）",
            "答案: 不可退",
        ),
    ]
    return self_consistency_vote(traces)


# ---------------------------------------------------------------------------
# 3) ToT：树节点扩展 + 评估剪枝（示意，不接真模型）
# ---------------------------------------------------------------------------


@dataclass
class ToTNode:
    id: str
    thought: str
    score: float
    children: list["ToTNode"] = field(default_factory=list)


def tot_expand(node: ToTNode, depth: int, branch: int) -> None:
    """伪扩展：每层 branch 个候选，depth 层后停止。"""
    if depth <= 0:
        return
    for i in range(branch):
        child = ToTNode(
            id=f"{node.id}.{i + 1}",
            thought=f"候选方案 {node.id}.{i + 1} @depth_left={depth}",
            # 假装评估器打分：靠后的分支略差，便于剪枝演示
            score=max(0.0, node.score - 0.15 * i - 0.05 * (3 - depth)),
        )
        node.children.append(child)
        tot_expand(child, depth - 1, branch)


def tot_prune(node: ToTNode, keep: int) -> None:
    """每层只保留 score 最高的 keep 个孩子（beam）。"""
    if not node.children:
        return
    node.children.sort(key=lambda n: n.score, reverse=True)
    node.children = node.children[:keep]
    for c in node.children:
        tot_prune(c, keep)


def tot_count(node: ToTNode) -> int:
    return 1 + sum(tot_count(c) for c in node.children)


def build_tot_protocol_prompt(question: str) -> list[dict[str, str]]:
    """ToT 的 prompt 形态：描述扩展/评估/剪枝协议（真正搜索在编排层）。"""
    return [
        {
            "role": "system",
            "content": (
                "你在 Tree-of-Thought 协议下工作。\n"
                "每一轮输出 JSON：\n"
                '{"stage":"expand|evaluate|finish","candidates":[...],"scores":[...],"choice":...}\n'
                "expand: 给出多个不同中间思路；evaluate: 给候选 0~1 分；"
                "finish: 输出最终答案。不要跳过评估。"
            ),
        },
        {"role": "user", "content": question},
    ]


def demo_tot(depth: int = 2, branch: int = 3, beam: int = 2) -> dict[str, Any]:
    root = ToTNode(id="0", thought="root: 理解用户退货诉求", score=1.0)
    # 若不剪枝，节点数 ≈ 1 + b + b^2 + ...；beam < branch 时剪枝才看得见
    tot_expand(root, depth=depth, branch=branch)
    unpruned = tot_count(root)
    # 重新建树再剪：避免在已统计树上原地改
    root_pruned = ToTNode(id="0", thought=root.thought, score=1.0)
    tot_expand(root_pruned, depth=depth, branch=branch)
    tot_prune(root_pruned, keep=beam)
    pruned = tot_count(root_pruned)
    return {
        "depth": depth,
        "branch": branch,
        "beam": beam,
        "nodes_before_prune": unpruned,
        "nodes_after_prune": pruned,
        "protocol_messages": build_tot_protocol_prompt(QUESTION),
        "cost_note": "费用随 展开节点数 增长，通常 ≫ Self-Consistency 的 N",
    }


# ---------------------------------------------------------------------------
# 4) ReAct：Thought → Action → Observation 循环（假工具）
# ---------------------------------------------------------------------------

ToolFn = Callable[[dict[str, Any]], dict[str, Any]]


def tool_get_logistics(args: dict[str, Any]) -> dict[str, Any]:
    oid = str(args.get("order_id", ""))
    return LOGISTICS.get(oid, {"error": "order_not_found"})


def tool_get_refund_policy(args: dict[str, Any]) -> dict[str, Any]:
    cat = str(args.get("category", "electronics"))
    if cat in REFUND_POLICY or cat == "electronics":
        return {
            "category": "electronics",
            "rule": REFUND_POLICY["electronics"],
            "window_days": REFUND_POLICY["window_days"],
        }
    return {"error": "unknown_category"}


TOOLS: dict[str, ToolFn] = {
    "get_logistics": tool_get_logistics,
    "get_refund_policy": tool_get_refund_policy,
}


@dataclass
class ReactStep:
    thought: str
    action: str | None = None
    action_input: dict[str, Any] | None = None
    observation: dict[str, Any] | None = None
    final_answer: str | None = None


def build_react_system() -> str:
    return (
        "你是带工具的客服 Agent。严格按协议输出：\n"
        "Thought: ...\n"
        "Action: <tool_name|finish>\n"
        "Action Input: <JSON>\n"
        "可用工具：get_logistics(order_id), get_refund_policy(category)。\n"
        "Observation 由系统写入，禁止自己编造 Observation。\n"
        "结束时 Action=finish，Action Input 为 {\"answer\": \"...\"}。"
    )


def run_react_simulated(question: str) -> list[ReactStep]:
    """
    不调用 LLM：按「理想策略」走固定轨迹，演示环与工具回填。
    真实系统里每步 Thought/Action 由模型生成，Observation 仍必须工具返回。
    """
    steps: list[ReactStep] = []

    s1 = ReactStep(
        thought="需要先确认订单 8821 物流/签收状态。",
        action="get_logistics",
        action_input={"order_id": "8821"},
    )
    s1.observation = TOOLS[s1.action](s1.action_input or {})
    steps.append(s1)

    s2 = ReactStep(
        thought="已签收。耳机属电子产品，查退货政策窗口。",
        action="get_refund_policy",
        action_input={"category": "electronics"},
    )
    s2.observation = TOOLS[s2.action](s2.action_input or {})
    steps.append(s2)

    signed = s1.observation or {}
    policy = s2.observation or {}
    answer = (
        f"物流：{signed.get('status')}（{signed.get('signed_at')}）。"
        f"政策：{policy.get('rule')} "
        f"结论：在 {policy.get('window_days')} 天内且质量问题，可退；请提供开箱视频。"
    )
    steps.append(
        ReactStep(
            thought="信息足够，给出结论。",
            action="finish",
            action_input={"answer": answer},
            final_answer=answer,
        )
    )
    return steps


def react_steps_to_messages(question: str, steps: list[ReactStep]) -> list[dict[str, str]]:
    """把轨迹展开成可落日志 / 可喂回模型的 messages 形态。"""
    msgs: list[dict[str, str]] = [
        {"role": "system", "content": build_react_system()},
        {"role": "user", "content": question},
    ]
    for st in steps:
        block = f"Thought: {st.thought}\n"
        if st.action:
            block += f"Action: {st.action}\n"
            block += f"Action Input: {json.dumps(st.action_input or {}, ensure_ascii=False)}\n"
        msgs.append({"role": "assistant", "content": block.strip()})
        if st.observation is not None:
            msgs.append(
                {
                    "role": "user",
                    "content": "Observation: "
                    + json.dumps(st.observation, ensure_ascii=False),
                }
            )
        if st.final_answer:
            msgs.append(
                {
                    "role": "assistant",
                    "content": f"Final Answer: {st.final_answer}",
                }
            )
    return msgs


# ---------------------------------------------------------------------------
# 5) Reflection：draft → critique → revise
# ---------------------------------------------------------------------------


def build_reflection_pipeline(question: str, draft: str) -> list[dict[str, str]]:
    """三阶段消息：可拆成 3 次调用，也可同会话多轮。"""
    return [
        {
            "role": "system",
            "content": "阶段1 Generate：回答用户，先给初稿。",
        },
        {"role": "user", "content": question},
        {"role": "assistant", "content": draft},
        {
            "role": "user",
            "content": (
                "阶段2 Reflect：只从【事实是否有依据 / 是否遗漏物流或政策 / 格式是否可执行】"
                "三点批评初稿，列出编号问题；不要重写全文。"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "1. 事实：初稿未引用具体签收日与政策原文。\n"
                "2. 遗漏：没说明需要开箱视频。\n"
                "3. 格式：结论与下一步动作混在一起，用户不好执行。"
            ),
        },
        {
            "role": "user",
            "content": "阶段3 Revise：按批评逐条修改，输出终稿。",
        },
        {
            "role": "assistant",
            "content": (
                "终稿：订单 8821 已于 2026-07-12 签收；电子产品签收 7 天内质量问题可退，"
                "需提供开箱视频。请在订单页提交售后并上传视频，我们将加急审核。"
            ),
        },
    ]


# ---------------------------------------------------------------------------
# 展示 & 主流程
# ---------------------------------------------------------------------------


def pretty_messages(messages: list[dict[str, str]], title: str, limit: int = 160) -> None:
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")
    print(f"消息条数: {len(messages)}")
    for i, m in enumerate(messages):
        body = m["content"]
        preview = body if len(body) <= limit else body[:limit] + "…"
        print(f"  [{i}] {m['role'].upper():10} | {preview}")


def cost_row(name: str, calls: str, note: str) -> str:
    return f"  {name:<18} | 调用量级: {calls:<12} | {note}"


def main() -> None:
    print("Reasoning Patterns Demo · 模块 02 Day6")
    print(f"题面: {QUESTION}\n")

    # 1. Direct vs CoT
    direct = build_direct_messages(QUESTION)
    cot = build_cot_messages(QUESTION)
    pretty_messages(direct, "1) 直接答（无显式推理协议）")
    pretty_messages(cot, "2) CoT（system 要求步骤 + 最终『答案:』）")
    assert len(direct) == len(cot), "CoT 不应无故增加消息条数"
    print("✓ CoT 与直接答消息条数相同：改的是协议，不是多轮结构")

    # 2. Self-Consistency
    sc = demo_self_consistency()
    print(f"\n{'=' * 64}\n3) Self-Consistency 投票（N={sc['n']} 伪轨迹）\n{'=' * 64}")
    print(f"  tally   : {sc['tally']}")
    print(f"  winner  : {sc['winner']}  ({sc['votes']}/{sc['n']} 票)")
    print(f"  代价因子: ×{sc['cost_factor']}（可并行降墙钟，费用仍 ×N）")
    assert sc["votes"] >= 3
    print("✓ 多数票胜出；机制是『多样本+投票』，不是单次更长思维")

    # 3. ToT
    tot = demo_tot()  # 默认 depth=2, branch=3, beam=2 → 剪枝前 1+3+9=13，剪枝后更少
    pretty_messages(tot["protocol_messages"], "4) ToT 协议 Prompt（搜索在编排层）")
    print(
        f"  树节点: 剪枝前 {tot['nodes_before_prune']} → 剪枝后 {tot['nodes_after_prune']}"
        f"  (depth={tot['depth']}, branch={tot['branch']}, beam={tot['beam']})"
    )
    print(f"  代价提示: {tot['cost_note']}")
    assert tot["nodes_after_prune"] <= tot["nodes_before_prune"]
    print("✓ beam 剪枝压节点数；ToT 成本跟展开宽度/深度走")

    # 4. ReAct
    steps = run_react_simulated(QUESTION)
    react_msgs = react_steps_to_messages(QUESTION, steps)
    pretty_messages(react_msgs, "5) ReAct 循环轨迹（Observation 来自假工具）", limit=200)
    tool_calls = [s for s in steps if s.action and s.action != "finish"]
    assert all(s.observation is not None for s in tool_calls)
    assert steps[-1].final_answer
    print(f"  工具步数: {len(tool_calls)}  终局: finish")
    print(f"  Final  : {steps[-1].final_answer[:80]}…")
    # 红线：Observation 不得由「模型自述」产生——本 demo 全部走 TOOLS
    print("✓ 每个 Action 的 Observation 均由 TOOLS 回填，无自编观测")

    # 5. Reflection
    weak_draft = "可以退的，您申请一下就行。"
    ref_msgs = build_reflection_pipeline(QUESTION, weak_draft)
    pretty_messages(ref_msgs, "6) Reflection 三阶段（Generate → Reflect → Revise）")
    assert any("开箱视频" in m["content"] for m in ref_msgs)
    print("✓ 终稿补上政策要点；Reflection 用 +2 阶段换质量，而非 ×N 采样")

    # 对比表
    print(f"\n{'=' * 64}\n代价对照（工程选型抓手）\n{'=' * 64}")
    print(cost_row("直接答", "1", "最便宜，复杂题易跳步"))
    print(cost_row("CoT", "1", "同调用量，多输出 token"))
    print(cost_row("Self-Consistency", f"N(={sc['n']})", "离散答案投票提稳"))
    print(cost_row("ToT", "≫N", "节点扩展+评估，规划题"))
    print(cost_row("ReAct", "1+工具轮次", "外部真值，防瞎编"))
    print(cost_row("Reflection", "1+2 阶段", "低成本质量插件"))

    print("\n结论:")
    print("  · CoT：最低改造成本的推理增强，先写步骤再给答案")
    print("  · SC：用 temperature 制造路径多样性，再投票；贪心采样会废掉 SC")
    print("  · ToT：树搜索思想，生产上常落成 Agent 编排而非纯长 prompt")
    print("  · ReAct：Thought⇄Action⇄Observation，Agent 最小内核")
    print("  · Reflection：生成后自检，可叠在任意路径后")
    print("  · 选型看 任务难度 × 延迟/费用预算，无银弹")


if __name__ == "__main__":
    main()
