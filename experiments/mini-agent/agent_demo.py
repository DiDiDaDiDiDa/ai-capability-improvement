#!/usr/bin/env python3
"""
Mini Agent 对照 Demo（模块 04）。
纯 Python 标准库：ReAct Loop + Memory + Planning + Tool Schema + Supervisor-Worker。

定位：
  模块 02 ReAct  是「推理路径」协议示意
  模块 04 Agent  是「可运行循环」：工具注册 / 记忆 / 规划 / 停止条件 / 多 agent

五个抓手（对应 README 五块）：
  1) Agent Loop   Thought→Action→Observe，max_turns 防死循环
  2) Memory       Short(transcript) / Long(KV) / Vector(语义召回)
  3) Planning     Plan-and-Execute vs ReAct 对照
  4) Tool         JSON Schema 注册表 + Function Calling 语义
  5) Multi-Agent  Supervisor 路由 → Worker 专岗

运行: python3 agent_demo.py
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# 0) 业务世界：订单 / 政策 / 知识库（工具的真实数据源）
# ---------------------------------------------------------------------------

LOGISTICS_DB = {
    "8821": {"status": "已签收", "signed_at": "2026-07-12", "item": "耳机", "category": "electronics"},
    "9001": {"status": "运输中", "signed_at": None, "item": "键盘", "category": "electronics"},
}

REFUND_POLICY = {
    "electronics": {"rule": "签收 7 天内质量问题可退，需开箱视频", "window_days": 7},
    "food": {"rule": "食品售出不退", "window_days": 0},
}

# 长期记忆种子：跨会话偏好 / 事实
LONG_TERM_SEED = {
    "user:u1:prefer_lang": "zh",
    "user:u1:vip": "true",
    "fact:refund_need_video": "质量问题退货需开箱视频",
}

# 向量记忆语料：历史工单摘要
VECTOR_MEMORY_DOCS = [
    ("m1", "用户 8821 耳机质量问题，已签收，走 7 天退货"),
    ("m2", "用户问食堂班车，与退货无关"),
    ("m3", "VIP 用户退货优先人工复核"),
]


# ---------------------------------------------------------------------------
# 1) Tool：JSON Schema 注册 + 分发（Function Calling 语义）
# ---------------------------------------------------------------------------

ToolFn = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema 子集
    handler: ToolFn = field(repr=False, compare=False)

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def _require(args: dict[str, Any], key: str) -> Any:
    if key not in args or args[key] in (None, ""):
        raise ValueError(f"missing required arg: {key}")
    return args[key]


def tool_get_logistics(args: dict[str, Any]) -> dict[str, Any]:
    oid = str(_require(args, "order_id"))
    row = LOGISTICS_DB.get(oid)
    if not row:
        return {"ok": False, "error": "order_not_found", "order_id": oid}
    return {"ok": True, "order_id": oid, **row}


def tool_get_refund_policy(args: dict[str, Any]) -> dict[str, Any]:
    cat = str(args.get("category") or "electronics")
    pol = REFUND_POLICY.get(cat)
    if not pol:
        return {"ok": False, "error": "unknown_category", "category": cat}
    return {"ok": True, "category": cat, **pol}


def tool_calc_days_since(args: dict[str, Any]) -> dict[str, Any]:
    """教学用：固定「今天」= 2026-07-15，算签收后天数。"""
    signed = str(_require(args, "signed_at"))
    # 极简日期差 YYYY-MM-DD
    def _ord(s: str) -> int:
        y, m, d = map(int, s.split("-"))
        return y * 372 + m * 31 + d

    today = "2026-07-15"
    return {"ok": True, "signed_at": signed, "today": today, "days": _ord(today) - _ord(signed)}


def tool_search_kb(args: dict[str, Any]) -> dict[str, Any]:
    q = str(_require(args, "query")).lower()
    hits = []
    for oid, row in LOGISTICS_DB.items():
        blob = json.dumps(row, ensure_ascii=False).lower()
        if q in blob or q in oid:
            hits.append({"order_id": oid, **row})
    return {"ok": True, "hits": hits[:3]}


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "get_logistics": ToolSpec(
        name="get_logistics",
        description="查询订单物流与签收状态",
        parameters={
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "订单号"}},
            "required": ["order_id"],
        },
        handler=tool_get_logistics,
    ),
    "get_refund_policy": ToolSpec(
        name="get_refund_policy",
        description="查询品类退货政策",
        parameters={
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": [],
        },
        handler=tool_get_refund_policy,
    ),
    "calc_days_since": ToolSpec(
        name="calc_days_since",
        description="计算签收日至今天的天数",
        parameters={
            "type": "object",
            "properties": {"signed_at": {"type": "string"}},
            "required": ["signed_at"],
        },
        handler=tool_calc_days_since,
    ),
    "search_kb": ToolSpec(
        name="search_kb",
        description="在订单知识库里关键词搜索",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=tool_search_kb,
    ),
}


def validate_args(spec: ToolSpec, args: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    req = spec.parameters.get("required") or []
    props = spec.parameters.get("properties") or {}
    for k in req:
        if k not in args:
            errs.append(f"missing:{k}")
    for k in args:
        if k not in props:
            errs.append(f"unknown:{k}")
    return errs


def dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_REGISTRY:
        return {"ok": False, "error": "unknown_tool", "tool": name}
    spec = TOOL_REGISTRY[name]
    errs = validate_args(spec, args)
    if errs:
        return {"ok": False, "error": "invalid_args", "detail": errs}
    try:
        return spec.handler(args)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "handler_exception", "detail": str(e)}


# ---------------------------------------------------------------------------
# 2) Memory：Short / Long / Vector
# ---------------------------------------------------------------------------

@dataclass
class ShortMemory:
    """对话/轨迹窗口：有上限的 list，模拟 context window。"""

    max_turns: int = 12
    turns: list[dict[str, Any]] = field(default_factory=list)

    def add(self, role: str, content: Any) -> None:
        self.turns.append({"role": role, "content": content})
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns :]

    def as_text(self) -> str:
        lines = []
        for t in self.turns:
            lines.append(f"{t['role']}: {t['content']}")
        return "\n".join(lines)


@dataclass
class LongMemory:
    """跨会话 KV：写入策略=显式 put；召回=精确 key / 前缀。"""

    store: dict[str, str] = field(default_factory=dict)

    def put(self, key: str, value: str) -> None:
        self.store[key] = value

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.store.get(key, default)

    def prefix(self, pfx: str) -> dict[str, str]:
        return {k: v for k, v in self.store.items() if k.startswith(pfx)}


def _embed(text: str, dim: int = 64) -> list[float]:
    t = re.sub(r"\s+", "", text.lower())
    vec = [0.0] * dim
    if not t:
        return vec
    grams = [t[i : i + 2] for i in range(max(1, len(t) - 1))]
    for g in grams:
        idx = int(hashlib.md5(g.encode()).hexdigest()[:8], 16) % dim
        vec[idx] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass
class VectorMemory:
    """语义召回历史：教学 n-gram 向量。"""

    ids: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    vecs: list[list[float]] = field(default_factory=list)

    def add(self, mid: str, text: str) -> None:
        self.ids.append(mid)
        self.texts.append(text)
        self.vecs.append(_embed(text))

    def search(self, query: str, top_k: int = 2) -> list[tuple[float, str, str]]:
        qv = _embed(query)
        scored = [(_dot(qv, self.vecs[i]), self.ids[i], self.texts[i]) for i in range(len(self.ids))]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


@dataclass
class AgentMemory:
    short: ShortMemory = field(default_factory=ShortMemory)
    long: LongMemory = field(default_factory=LongMemory)
    vector: VectorMemory = field(default_factory=VectorMemory)

    def bootstrap(self) -> None:
        for k, v in LONG_TERM_SEED.items():
            self.long.put(k, v)
        for mid, text in VECTOR_MEMORY_DOCS:
            self.vector.add(mid, text)


# ---------------------------------------------------------------------------
# 3) Agent Loop：ReAct + 停止条件
# ---------------------------------------------------------------------------

@dataclass
class Step:
    thought: str
    action: str
    action_input: dict[str, Any]
    observation: dict[str, Any] | None = None
    final_answer: str | None = None


@dataclass
class AgentResult:
    answer: str
    steps: list[Step]
    stopped_reason: str  # finish | max_turns | error
    used_tools: list[str]


# 教学版「策略 LLM」：根据问题与已有 observation 决定下一步 Action
# 生产：换成真 LLM 解析 Thought/Action；接口保持 run_react(policy=...)

def policy_refund_react(question: str, history: list[Step], memory: AgentMemory) -> Step:
    """理想策略：物流 → 天数 → 政策 → finish。"""
    obs = {s.action: s.observation for s in history if s.observation is not None}
    # 抽订单号
    m = re.search(r"\b(\d{4,})\b", question)
    order_id = m.group(1) if m else "8821"

    if "get_logistics" not in obs:
        return Step(
            thought=f"先查订单 {order_id} 物流/签收。",
            action="get_logistics",
            action_input={"order_id": order_id},
        )
    logi = obs["get_logistics"] or {}
    if not logi.get("ok"):
        return Step(
            thought="订单不存在，结束。",
            action="finish",
            action_input={"answer": f"未找到订单 {order_id}。"},
            final_answer=f"未找到订单 {order_id}。",
        )
    if logi.get("status") != "已签收":
        return Step(
            thought="未签收，不能退货。",
            action="finish",
            action_input={"answer": f"订单 {order_id} 状态为{logi.get('status')}，尚未签收，暂不能退货。"},
            final_answer=f"订单 {order_id} 状态为{logi.get('status')}，尚未签收，暂不能退货。",
        )
    if "calc_days_since" not in obs and logi.get("signed_at"):
        return Step(
            thought="已签收，算签收天数是否在窗口内。",
            action="calc_days_since",
            action_input={"signed_at": logi["signed_at"]},
        )
    if "get_refund_policy" not in obs:
        cat = logi.get("category") or "electronics"
        return Step(
            thought=f"查 {cat} 退货政策。",
            action="get_refund_policy",
            action_input={"category": cat},
        )
    days = (obs.get("calc_days_since") or {}).get("days", 999)
    pol = obs.get("get_refund_policy") or {}
    window = int(pol.get("window_days") or 0)
    vip = memory.long.get("user:u1:vip") == "true"
    need_video = memory.long.get("fact:refund_need_video", "")
    if days <= window:
        ans = (
            f"订单 {order_id} 已签收 {days} 天，政策窗口 {window} 天内："
            f"{pol.get('rule')}。结论：可退。"
            f"{'VIP 优先复核。' if vip else ''}"
            f"补充：{need_video}"
        )
    else:
        ans = f"订单 {order_id} 已签收 {days} 天，超过 {window} 天窗口，不可退。"
    return Step(
        thought="信息足够，finish。",
        action="finish",
        action_input={"answer": ans},
        final_answer=ans,
    )


def run_react(
    question: str,
    memory: AgentMemory,
    policy: Callable[[str, list[Step], AgentMemory], Step] = policy_refund_react,
    max_turns: int = 6,
) -> AgentResult:
    memory.short.add("user", question)
    steps: list[Step] = []
    used: list[str] = []
    for _ in range(max_turns):
        step = policy(question, steps, memory)
        if step.action == "finish":
            ans = step.final_answer or str((step.action_input or {}).get("answer", ""))
            step.final_answer = ans
            steps.append(step)
            memory.short.add("assistant", ans)
            # 写入 vector 记忆一条轨迹摘要
            memory.vector.add(f"traj-{len(memory.vector.ids)+1}", f"Q:{question} A:{ans[:80]}")
            return AgentResult(answer=ans, steps=steps, stopped_reason="finish", used_tools=used)
        obs = dispatch_tool(step.action, step.action_input or {})
        step.observation = obs
        steps.append(step)
        used.append(step.action)
        memory.short.add("tool", {"action": step.action, "obs": obs})
    # 死循环保护
    return AgentResult(
        answer="达到 max_turns，停止（防止死循环）。",
        steps=steps,
        stopped_reason="max_turns",
        used_tools=used,
    )


# ---------------------------------------------------------------------------
# 4) Planning：Plan-and-Execute
# ---------------------------------------------------------------------------

@dataclass
class SubTask:
    id: str
    description: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending|done|failed|skipped
    result: dict[str, Any] | None = None


def build_refund_plan(order_id: str) -> list[SubTask]:
    return [
        SubTask("t1", "查物流", "get_logistics", {"order_id": order_id}),
        SubTask("t2", "算签收天数", "calc_days_since", {}, depends_on=["t1"]),
        SubTask("t3", "查退货政策", "get_refund_policy", {}, depends_on=["t1"]),
        SubTask("t4", "汇总结论", None, {}, depends_on=["t2", "t3"]),
    ]


def run_plan_execute(order_id: str, max_retries: int = 1) -> tuple[str, list[SubTask]]:
    plan = build_refund_plan(order_id)
    by_id = {t.id: t for t in plan}
    for task in plan:
        if any(by_id[d].status != "done" for d in task.depends_on):
            task.status = "skipped"
            continue
        if task.tool is None:
            # 汇总
            logi = by_id["t1"].result or {}
            days = (by_id["t2"].result or {}).get("days")
            pol = by_id["t3"].result or {}
            if not logi.get("ok"):
                task.result = {"answer": f"未找到订单 {order_id}"}
                task.status = "done"
                continue
            if logi.get("status") != "已签收":
                task.result = {"answer": f"订单未签收（{logi.get('status')}），不可退"}
                task.status = "done"
                continue
            window = int(pol.get("window_days") or 0)
            ok = days is not None and days <= window
            task.result = {
                "answer": (
                    f"[Plan] 订单 {order_id} 签收 {days} 天 / 窗口 {window} 天 → "
                    f"{'可退' if ok else '不可退'}。{pol.get('rule', '')}"
                )
            }
            task.status = "done"
            continue
        # 填依赖产生的参数
        args = dict(task.args)
        if task.id == "t2":
            args["signed_at"] = (by_id["t1"].result or {}).get("signed_at") or "1970-01-01"
        if task.id == "t3":
            args["category"] = (by_id["t1"].result or {}).get("category") or "electronics"
        last_err = None
        for _ in range(max_retries + 1):
            res = dispatch_tool(task.tool, args)
            if res.get("ok"):
                task.result = res
                task.status = "done"
                break
            last_err = res
        else:
            task.result = last_err
            task.status = "failed"
    final = by_id["t4"].result or {"answer": "计划未完成"}
    return str(final.get("answer", "")), plan


# ---------------------------------------------------------------------------
# 5) Multi-Agent：Supervisor → Worker
# ---------------------------------------------------------------------------

def worker_logistics(question: str) -> str:
    m = re.search(r"\b(\d{4,})\b", question)
    oid = m.group(1) if m else ""
    if not oid:
        return "物流专员：未识别订单号。"
    r = dispatch_tool("get_logistics", {"order_id": oid})
    if not r.get("ok"):
        return f"物流专员：订单 {oid} 不存在。"
    return f"物流专员：{oid} → {r.get('status')} 签收日 {r.get('signed_at')}"


def worker_policy(question: str) -> str:
    cat = "electronics" if any(k in question for k in ("耳机", "键盘", "电子")) else "electronics"
    r = dispatch_tool("get_refund_policy", {"category": cat})
    return f"政策专员：{r.get('rule')}（{r.get('window_days')} 天）"


def worker_chitchat(question: str) -> str:
    return "闲聊专员：我是客服助手，可查物流与退货政策。"


WORKERS: dict[str, Callable[[str], str]] = {
    "logistics": worker_logistics,
    "policy": worker_policy,
    "chitchat": worker_chitchat,
}


def supervisor_route(question: str) -> str:
    q = question.lower()
    if any(k in question for k in ("退", "政策", "能否退", "可退")):
        # 退货往往需要两路：先物流再政策——supervisor 串起来
        return "refund_pipeline"
    if any(k in question for k in ("物流", "到哪", "签收", "订单")) or re.search(r"\d{4,}", question):
        return "logistics"
    if any(k in question for k in ("你好", "你是谁", "天气")):
        return "chitchat"
    return "chitchat"


def run_supervisor(question: str) -> dict[str, Any]:
    route = supervisor_route(question)
    if route == "refund_pipeline":
        a = WORKERS["logistics"](question)
        b = WORKERS["policy"](question)
        answer = f"{a}\n{b}\n主管汇总：请结合签收日与政策窗口判断是否可退。"
        return {"route": route, "workers": ["logistics", "policy"], "answer": answer}
    w = WORKERS[route]
    return {"route": route, "workers": [route], "answer": w(question)}


# ---------------------------------------------------------------------------
# Demo + 断言
# ---------------------------------------------------------------------------

def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def demo_tools() -> None:
    section("1) Tool：JSON Schema 注册 + 校验 + 分发")
    schemas = [t.schema() for t in TOOL_REGISTRY.values()]
    print(f"  registered tools: {[s['name'] for s in schemas]}")
    ok = dispatch_tool("get_logistics", {"order_id": "8821"})
    bad = dispatch_tool("get_logistics", {})
    unknown = dispatch_tool("fly_to_moon", {})
    print(f"  ok: {ok}")
    print(f"  missing arg: {bad}")
    print(f"  unknown tool: {unknown}")
    assert ok.get("ok") and ok.get("status") == "已签收"
    assert bad.get("error") == "invalid_args"
    assert unknown.get("error") == "unknown_tool"
    assert "parameters" in TOOL_REGISTRY["get_logistics"].schema()
    print("  → Function Calling 语义：模型只出 name+arguments，执行在宿主侧")


def demo_memory() -> None:
    section("2) Memory：Short / Long / Vector")
    mem = AgentMemory()
    mem.bootstrap()
    mem.short.add("user", "我想退货")
    mem.short.add("assistant", "请提供订单号")
    assert len(mem.short.turns) == 2
    assert mem.long.get("user:u1:vip") == "true"
    hits = mem.vector.search("8821 耳机退货", top_k=1)
    print(f"  long vip={mem.long.get('user:u1:vip')}")
    print(f"  vector top1: {hits[0][1]} score={hits[0][0]:.3f} | {hits[0][2]}")
    assert hits[0][1] == "m1", "语义召回应命中 8821 退货历史"
    # 窗口截断
    sm = ShortMemory(max_turns=3)
    for i in range(5):
        sm.add("user", str(i))
    assert len(sm.turns) == 3 and sm.turns[0]["content"] == "2"
    print("  short window truncates to last 3 turns")
    print("  → Short=上下文；Long=跨会话 KV；Vector=语义历史")


def demo_react_loop() -> None:
    section("3) Agent Loop：ReAct + max_turns")
    mem = AgentMemory()
    mem.bootstrap()
    q = "订单 8821 的耳机到货就坏了，能退吗？"
    result = run_react(q, mem, max_turns=6)
    print(f"Q: {q}")
    for i, s in enumerate(result.steps, 1):
        print(f"  step{i}: Thought={s.thought}")
        print(f"         Action={s.action} input={s.action_input}")
        if s.observation is not None:
            print(f"         Obs={s.observation}")
        if s.final_answer:
            print(f"         Final={s.final_answer}")
    print(f"  stopped={result.stopped_reason} tools={result.used_tools}")
    assert result.stopped_reason == "finish"
    assert "get_logistics" in result.used_tools
    assert "get_refund_policy" in result.used_tools
    assert "可退" in result.answer
    assert "3" in result.answer or "天" in result.answer  # 签收后天数
    # 死循环保护：永远不 finish 的 policy
    def bad_policy(question: str, history: list[Step], memory: AgentMemory) -> Step:
        return Step("loop", "get_logistics", {"order_id": "8821"})

    mem2 = AgentMemory()
    stuck = run_react("x", mem2, policy=bad_policy, max_turns=3)
    assert stuck.stopped_reason == "max_turns"
    assert len(stuck.steps) == 3
    print("  max_turns guard: forced stop after 3")
    print("  → Observation 必须工具回填；finish / max_turns 双停止条件")


def demo_planning() -> None:
    section("4) Planning：Plan-and-Execute vs ReAct")
    ans, plan = run_plan_execute("8821")
    print(f"  plan answer: {ans}")
    for t in plan:
        print(f"    {t.id} [{t.status}] {t.description} → {t.result}")
    assert all(t.status in {"done", "skipped"} for t in plan)
    done_tasks = [t for t in plan if t.status == "done"]
    assert done_tasks, "计划应有完成的子任务"
    assert "可退" in ans
    # 对比：ReAct 动态分支，Plan 先拆后执行
    mem = AgentMemory()
    mem.bootstrap()
    react = run_react("订单 9001 能退吗？", mem)  # 运输中
    pe_ans, pe_plan = run_plan_execute("9001")
    print(f"  9001 react: {react.answer}")
    print(f"  9001 plan : {pe_ans}")
    assert "不可退" in react.answer or "不能" in react.answer or "尚未" in react.answer
    assert "不可退" in pe_ans or "未签收" in pe_ans
    print("  → Plan-and-Execute 适合依赖清晰的批处理；ReAct 适合观察后分支")


def demo_multi_agent() -> None:
    section("5) Multi-Agent：Supervisor-Worker")
    cases = [
        ("订单 8821 到哪了", "logistics"),
        ("耳机退货政策是什么", "refund_pipeline"),
        ("你好你是谁", "chitchat"),
    ]
    for q, expect_route in cases:
        out = run_supervisor(q)
        print(f"Q: {q}")
        print(f"  route={out['route']} workers={out['workers']}")
        print(f"  answer: {out['answer'][:80]}...")
        assert out["route"] == expect_route, f"route want {expect_route} got {out['route']}"
    # 协调开销：简单闲聊不该上多 worker
    chat = run_supervisor("你好")
    assert chat["workers"] == ["chitchat"]
    print("  → 多 agent 有协调税；简单题单 worker，复杂退货才 pipeline")


def demo_p3_bridge() -> None:
    section("6) → P3 桥接：同一 Loop 可换工具集")
    # Coding agent 工具名不同，循环不变
    coding_tools = ["read_file", "search_code", "run_tests", "finish"]
    print(f"  customer tools: {list(TOOL_REGISTRY)}")
    print(f"  coding tools (P3): {coding_tools}")
    print("  不变的是：Thought→Action→Obs + max_turns + Memory；变的是 Tool 注册表")
    assert "finish" in coding_tools


def main() -> None:
    print("Mini Agent · Module 04 (stdlib: loop/memory/plan/tool/multi-agent)")
    demo_tools()
    demo_memory()
    demo_react_loop()
    demo_planning()
    demo_multi_agent()
    demo_p3_bridge()
    section("DONE · Module 04 mini-agent green")
    print("Agent = LLM + Memory + Planning + Tool + Observation + Reflection")
    print("next: P3 swaps tools to read/search/edit/run on a real repo")


if __name__ == "__main__":
    main()
