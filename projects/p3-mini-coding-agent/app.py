#!/usr/bin/env python3
"""
P3 Mini Coding Agent — 验收入口。

M1: ReAct + read/search（+ list_dir）
M2: edit_file + run_cmd（allowlist）
轻量 M3: 测试红→改→再跑；max_turns 防死循环
安全: Workspace 路径沙箱 + 命令白名单

运行:
  cd projects/p3-mini-coding-agent && python3 app.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from p3agent.gateway import GatewayPolicy, MockProvider, build_gateway_policy
from p3agent.loop import run_react
from p3agent.mcp_ext import build_demo_mcp_server, register_mcp_server
from p3agent.policy import policy_fix_add, policy_max_turns_noop, policy_path_escape_probe
from p3agent.tools import TOOL_REGISTRY, Workspace, dispatch_tool


ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "sandbox" / "sample_repo"


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def clone_sandbox() -> Path:
    """Each run gets a fresh copy so edits don't dirty the template."""
    tmp = Path(tempfile.mkdtemp(prefix="p3-sandbox-"))
    dest = tmp / "sample_repo"
    shutil.copytree(SAMPLE, dest)
    return dest


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def demo_tool_schemas() -> None:
    section("0) Tool registry (coding tools)")
    names = sorted(TOOL_REGISTRY.keys())
    print(f"  tools: {names}")
    assert_true(
        set(names) >= {"read_file", "search_code", "edit_file", "run_cmd", "list_dir"},
        "missing core coding tools",
    )


def demo_sandbox_guards(ws: Workspace) -> None:
    section("1) Sandbox guards: path escape + cmd allowlist")
    esc = dispatch_tool("read_file", {"path": "../../README.md"}, ws)
    print(f"  escape read: ok={esc.get('ok')} error={esc.get('error')}")
    assert_true(esc.get("ok") is False, "path escape must fail")
    assert_true(esc.get("error") == "path_error", f"expected path_error, got {esc}")

    bad = dispatch_tool("run_cmd", {"cmd": "rm -rf /"}, ws)
    print(f"  rm blocked: ok={bad.get('ok')} error={bad.get('error')}")
    assert_true(bad.get("ok") is False and bad.get("error") == "cmd_not_allowed", "rm must be blocked")


def demo_fix_loop() -> None:
    section("2) ReAct: search → read → run(red) → edit → run(green) → finish")
    work = clone_sandbox()
    ws = Workspace(work)

    # pre: tests must be red on buggy template
    red = dispatch_tool("run_cmd", {"cmd": "python3 test_calc.py"}, ws)
    print(f"  pre-test returncode={red.get('returncode')} ok={red.get('ok')}")
    assert_true(red.get("ok") is False, "fixture must fail before agent")

    task = "修复 calc.add 的 bug，让 test_calc.py 全绿，并给出 git commit 建议。"
    result = run_react(task, ws, policy=policy_fix_add, max_turns=10)

    print(f"  stopped_reason={result.stopped_reason}")
    print(f"  used_tools={result.used_tools}")
    print(f"  answer={result.answer}")
    print(f"  commit={result.commit_message}")
    for i, s in enumerate(result.steps, 1):
        ok = (s.observation or {}).get("ok") if s.observation else None
        print(f"    step{i}: {s.action} thought={s.thought[:40]}… obs_ok={ok}")

    assert_true(result.stopped_reason == "finish", "should finish")
    assert_true("search_code" in result.used_tools, "must search")
    assert_true("read_file" in result.used_tools, "must read")
    assert_true("edit_file" in result.used_tools, "must edit")
    assert_true("run_cmd" in result.used_tools, "must run tests")
    assert_true(result.commit_message is not None and "add" in result.commit_message.lower(), "commit msg")

    # post: file fixed + tests green
    fixed = (work / "calc.py").read_text(encoding="utf-8")
    assert_true("return a + b" in fixed, "calc.py should contain a + b")
    assert_true("return a - b" not in fixed, "bug line should be gone")
    green = dispatch_tool("run_cmd", {"cmd": "python3 test_calc.py"}, ws)
    assert_true(green.get("ok") is True, f"tests must pass after agent: {green}")

    # cleanup
    shutil.rmtree(work.parent, ignore_errors=True)
    print("  fix-loop: PASS")


def demo_max_turns() -> None:
    section("3) max_turns: bad policy forced stop")
    work = clone_sandbox()
    ws = Workspace(work)
    result = run_react("noop", ws, policy=policy_max_turns_noop, max_turns=3)
    print(f"  stopped_reason={result.stopped_reason} steps={len(result.steps)}")
    assert_true(result.stopped_reason == "max_turns", "must stop on max_turns")
    assert_true(len(result.steps) == 3, "exactly 3 steps")
    shutil.rmtree(work.parent, ignore_errors=True)
    print("  max_turns: PASS")


def demo_path_policy() -> None:
    section("4) policy path-escape probe")
    work = clone_sandbox()
    ws = Workspace(work)
    result = run_react("probe", ws, policy=policy_path_escape_probe, max_turns=4)
    print(f"  answer={result.answer}")
    assert_true(result.stopped_reason == "finish", "finish")
    assert_true(result.answer == "blocked", f"escape should be blocked, got {result.answer}")
    shutil.rmtree(work.parent, ignore_errors=True)
    print("  path-probe: PASS")


def demo_repo_map() -> None:
    section("5) M4 repo_map: ast 符号摘要（Aider 风格低 token 概览）")
    work = clone_sandbox()
    ws = Workspace(work)
    res = dispatch_tool("repo_map", {}, ws)
    print(f"  ok={res.get('ok')} files={res.get('files')} symbols={res.get('symbol_count')}")
    print("  --- map 摘录 ---")
    for line in (res.get("map") or "").splitlines()[:8]:
        print(f"    {line}")
    assert_true(res.get("ok") is True, "repo_map must succeed")
    assert_true("calc.py" in (res.get("files") or []), "must map calc.py")
    assert_true("geometry.py" in (res.get("files") or []), "must map geometry.py")
    # 符号至少覆盖 add/mul + circle_area + Point + TextStats 等
    assert_true(res.get("symbol_count", 0) >= 8, f"expected >=8 symbols, got {res.get('symbol_count')}")
    assert_true("class Point" in (res.get("map") or ""), "map should list Point class")
    shutil.rmtree(work.parent, ignore_errors=True)
    print("  repo_map: PASS")


def demo_retrieve() -> None:
    section("6) M4 retrieve_context: TF-IDF 预索引检索（Cursor 风格召回）")
    work = clone_sandbox()
    ws = Workspace(work)
    res = dispatch_tool("retrieve_context", {"query": "area of a circle", "top_k": 3}, ws)
    hits = res.get("hits") or []
    print(f"  ok={res.get('ok')} indexed={res.get('indexed_chunks')} top{len(hits)}:")
    for h in hits:
        print(f"    {h['score']:.3f}  {h['path']}:{h['line']}  {h['name']}")
    assert_true(res.get("ok") is True, "retrieve must succeed")
    assert_true(len(hits) >= 1, "must return hits")
    # 语义相关：'circle area' 应把 circle_area 排到第一
    assert_true(hits[0]["name"] == "circle_area", f"top hit should be circle_area, got {hits[0]['name']}")
    shutil.rmtree(work.parent, ignore_errors=True)
    print("  retrieve_context: PASS")


def demo_mcp_ext() -> None:
    section("7) M5 MCP 扩展: 外部工具动态注册进 registry（loop 零改动）")
    before = set(TOOL_REGISTRY.keys())
    server = build_demo_mcp_server()
    added = register_mcp_server(server, prefix="mcp")
    after = set(TOOL_REGISTRY.keys())
    print(f"  registered: {added}")
    print(f"  registry grew: {len(before)} → {len(after)}")
    assert_true("mcp.word_count" in after, "MCP tool must be registered")
    work = clone_sandbox()
    ws = Workspace(work)
    # 通过标准 dispatch_tool 调用外部工具（校验+分发一视同仁）
    res = dispatch_tool("mcp.word_count", {"text": "coding agent harness rules"}, ws)
    print(f"  call mcp.word_count → ok={res.get('ok')} words={res.get('words')}")
    assert_true(res.get("ok") is True and res.get("words") == 4, f"mcp tool exec: {res}")
    # 清理：注册表还原，避免污染后续（owner 意识）
    for name in added:
        TOOL_REGISTRY.pop(name, None)
    shutil.rmtree(work.parent, ignore_errors=True)
    print("  mcp_ext: PASS")


def demo_gateway() -> None:
    section("8) M5 Gateway 接缝: policy 里的 LLM 可热替换")
    work = clone_sandbox()
    ws = Workspace(work)
    red = dispatch_tool("run_cmd", {"cmd": "python3 test_calc.py"}, ws)
    assert_true(red.get("ok") is False, "fixture must be red")

    gw = build_gateway_policy(MockProvider())
    print(f"  provider={gw.provider.name} available_tools={len(gw.available_tools())}")
    assert_true(isinstance(gw, GatewayPolicy), "gateway policy built")
    assert_true(len(gw.available_tools()) >= 5, "gateway must expose tool schemas to LLM")

    task = "修复 calc.add 并让测试全绿。"
    result = run_react(task, ws, policy=gw, max_turns=10)  # gateway 直接当 PolicyFn 用
    print(f"  stopped={result.stopped_reason} commit={result.commit_message}")
    assert_true(result.stopped_reason == "finish", "gateway-driven run must finish")
    green = dispatch_tool("run_cmd", {"cmd": "python3 test_calc.py"}, ws)
    assert_true(green.get("ok") is True, "tests green via gateway policy")
    shutil.rmtree(work.parent, ignore_errors=True)
    print("  gateway: PASS（换 provider 即换模型，loop/工具零改动）")


def main() -> int:
    print("P3 Mini Coding Agent · M1–M5 acceptance")
    demo_tool_schemas()

    work = clone_sandbox()
    ws = Workspace(work)
    try:
        demo_sandbox_guards(ws)
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)

    demo_fix_loop()
    demo_max_turns()
    demo_path_policy()
    demo_repo_map()
    demo_retrieve()
    demo_mcp_ext()
    demo_gateway()

    section("DONE · P3 M1–M5 green")
    print("  M1 Loop | M2 Edit+Run | M3 Reflection | M4 RepoMap+Retrieve | M5 MCP+Gateway")
    print("EXIT:0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"ASSERT FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
