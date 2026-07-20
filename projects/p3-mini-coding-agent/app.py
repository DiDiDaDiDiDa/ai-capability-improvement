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

from p3agent.loop import run_react
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


def main() -> int:
    print("P3 Mini Coding Agent · M1+M2 acceptance")
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

    section("DONE · P3 M1+M2 green")
    print("EXIT:0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"ASSERT FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
