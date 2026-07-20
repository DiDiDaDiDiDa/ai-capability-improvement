"""
Mock coding policies (teaching LLM stand-in).

Production: swap for real LLM that emits Thought/Action JSON.
Interface stays: policy(task, history, workspace) -> Step
"""

from __future__ import annotations

from typing import Any

from .loop import Step
from .tools import Workspace


def _obs_map(history: list[Step]) -> dict[str, dict[str, Any]]:
    """Last observation per action name (later overwrites)."""
    out: dict[str, dict[str, Any]] = {}
    for s in history:
        if s.observation is not None:
            out[s.action] = s.observation
    return out


def _last(history: list[Step], action: str) -> dict[str, Any] | None:
    for s in reversed(history):
        if s.action == action and s.observation is not None:
            return s.observation
    return None


def policy_fix_add(task: str, history: list[Step], ws: Workspace) -> Step:
    """
    Ideal policy for: fix calc.add so tests pass.

    Path (M1+M2+light M3):
      list/search → read → run (red) → edit → run (green) → finish + commit msg
    """
    n = len(history)
    last_run = _last(history, "run_cmd")
    last_edit = _last(history, "edit_file")
    last_read = _last(history, "read_file")
    last_search = _last(history, "search_code")

    # 0) locate add / tests
    if last_search is None and n == 0:
        return Step(
            thought="先 agentic search 定位 add 与测试。",
            action="search_code",
            action_input={"query": "def add", "glob": "*.py"},
        )

    if last_read is None or not (last_read.get("ok") and "return a - b" in (last_read.get("content") or "")):
        # read calc if we haven't seen the bug line yet
        if last_read is None or last_read.get("path") != "calc.py":
            return Step(
                thought="读 calc.py 看 add 实现。",
                action="read_file",
                action_input={"path": "calc.py"},
            )

    # 1) red: run tests before edit (or after failed edit)
    if last_run is None:
        return Step(
            thought="先跑测试拿红灯，确认失败形态。",
            action="run_cmd",
            action_input={"cmd": "python3 test_calc.py"},
        )

    # 2) if tests green → finish
    if last_run.get("ok") is True and last_run.get("returncode") == 0:
        return Step(
            thought="测试全绿，finish 并给 commit 建议。",
            action="finish",
            action_input={
                "answer": "已修复 calc.add：a-b → a+b，test_calc 全绿。",
                "commit_message": "fix(calc): correct add to return a + b",
            },
            final_answer="已修复 calc.add：a-b → a+b，test_calc 全绿。",
        )

    # 3) red path → edit if not yet successfully edited to +
    if last_edit is None or not last_edit.get("ok"):
        return Step(
            thought="测试失败；把 add 的 a - b 改成 a + b。",
            action="edit_file",
            action_input={
                "path": "calc.py",
                "old_str": "return a - b",
                "new_str": "return a + b",
            },
        )

    # 4) edited but last run still red → re-run (reflection)
    if last_edit.get("ok") and not last_run.get("ok"):
        # if run was before edit, need another run
        # find whether any run_cmd happened after last successful edit
        edit_idx = max(i for i, s in enumerate(history) if s.action == "edit_file")
        run_after = any(
            s.action == "run_cmd" and s.observation and s.observation.get("ok")
            for s in history[edit_idx + 1 :]
        )
        if not run_after:
            return Step(
                thought="已改文件，重跑测试验证（reflection）。",
                action="run_cmd",
                action_input={"cmd": "python3 test_calc.py"},
            )

    # 5) fallback: list dir then search again
    return Step(
        thought="状态不清晰，列目录再定位。",
        action="list_dir",
        action_input={"path": "."},
    )


def policy_max_turns_noop(task: str, history: list[Step], ws: Workspace) -> Step:
    """Bad policy: always search → proves max_turns stop."""
    return Step(
        thought="无脑循环 search（用于 max_turns 断言）。",
        action="search_code",
        action_input={"query": "add"},
    )


def policy_path_escape_probe(task: str, history: list[Step], ws: Workspace) -> Step:
    """Try to escape sandbox then finish with observation."""
    if not history:
        return Step(
            thought="探测路径逃逸是否被拒。",
            action="read_file",
            action_input={"path": "../README.md"},
        )
    obs = history[0].observation or {}
    ok_blocked = obs.get("ok") is False and obs.get("error") in ("path_error", "not_found")
    # ../ from sandbox/sample_repo resolves outside → path_error
    return Step(
        thought="根据探测结果结束。",
        action="finish",
        action_input={
            "answer": "blocked" if ok_blocked or obs.get("error") == "path_error" else f"unexpected:{obs}",
        },
        final_answer="blocked" if (obs.get("error") == "path_error") else f"unexpected:{obs}",
    )
