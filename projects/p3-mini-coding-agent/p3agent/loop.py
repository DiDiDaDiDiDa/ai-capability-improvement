"""ReAct loop for coding agent — same skeleton as module 04, coding tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .tools import Workspace, dispatch_tool


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
    commit_message: str | None = None


PolicyFn = Callable[[str, list[Step], Workspace], Step]


def run_react(
    task: str,
    ws: Workspace,
    policy: PolicyFn,
    max_turns: int = 10,
) -> AgentResult:
    steps: list[Step] = []
    used: list[str] = []
    for _ in range(max_turns):
        step = policy(task, steps, ws)
        if step.action == "finish":
            ans = step.final_answer or str((step.action_input or {}).get("answer", ""))
            commit = (step.action_input or {}).get("commit_message")
            step.final_answer = ans
            steps.append(step)
            return AgentResult(
                answer=ans,
                steps=steps,
                stopped_reason="finish",
                used_tools=used,
                commit_message=str(commit) if commit else None,
            )
        obs = dispatch_tool(step.action, step.action_input or {}, ws)
        step.observation = obs
        steps.append(step)
        used.append(step.action)
    return AgentResult(
        answer="达到 max_turns，停止（防止死循环）。",
        steps=steps,
        stopped_reason="max_turns",
        used_tools=used,
    )


@dataclass
class ShortMemory:
    """Transcript of tool observations for reflection / debug."""

    turns: list[dict[str, Any]] = field(default_factory=list)

    def add_step(self, step: Step) -> None:
        self.turns.append(
            {
                "thought": step.thought,
                "action": step.action,
                "input": step.action_input,
                "obs_ok": (step.observation or {}).get("ok") if step.observation else None,
            }
        )
