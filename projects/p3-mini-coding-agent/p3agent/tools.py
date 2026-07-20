"""
Coding tools: read / search / edit / run (+ finish is loop-level).

Design (steal from Claude Code harness):
  - small orthogonal set
  - path confined to Workspace
  - run_cmd allowlist only (python/python3 + fixed args patterns)
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .workspace import Workspace, WorkspaceError

ToolFn = Callable[[dict[str, Any], Workspace], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
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


def tool_read_file(args: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    path = str(_require(args, "path"))
    try:
        p = ws.resolve(path)
    except WorkspaceError as e:
        return {"ok": False, "error": "path_error", "detail": str(e)}
    if not p.is_file():
        return {"ok": False, "error": "not_found", "path": path}
    text = p.read_text(encoding="utf-8")
    # observation 截断：防 context 爆
    max_chars = int(args.get("max_chars") or 8000)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n…[truncated]"
    return {
        "ok": True,
        "path": path,
        "content": text,
        "truncated": truncated,
        "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
    }


def tool_search_code(args: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """Substring / regex search under workspace (agentic search, no pre-index)."""
    query = str(_require(args, "query"))
    use_regex = bool(args.get("regex") or False)
    glob_suffix = str(args.get("glob") or "*.py")
    max_hits = int(args.get("max_hits") or 20)

    try:
        pattern = re.compile(query) if use_regex else None
    except re.error as e:
        return {"ok": False, "error": "bad_regex", "detail": str(e)}

    hits: list[dict[str, Any]] = []
    for p in sorted(ws.root.rglob(glob_suffix)):
        if not p.is_file():
            continue
        # skip caches
        if any(part.startswith(".") or part == "__pycache__" for part in p.parts):
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        rel = ws.relpath(p)
        for i, line in enumerate(lines, 1):
            if pattern is not None:
                if not pattern.search(line):
                    continue
            else:
                if query not in line:
                    continue
            hits.append({"path": rel, "line": i, "text": line.strip()[:200]})
            if len(hits) >= max_hits:
                return {"ok": True, "query": query, "hits": hits, "hit_count": len(hits)}
    return {"ok": True, "query": query, "hits": hits, "hit_count": len(hits)}


def tool_edit_file(args: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """
    Structured edit (Aider-style stability):
      - old_str must appear exactly once (or replace_all=true)
      - new_str replaces it
    """
    path = str(_require(args, "path"))
    old = str(_require(args, "old_str"))
    new = str(args.get("new_str") if "new_str" in args else _require(args, "new_str"))
    replace_all = bool(args.get("replace_all") or False)

    try:
        p = ws.resolve(path)
    except WorkspaceError as e:
        return {"ok": False, "error": "path_error", "detail": str(e)}
    if not p.is_file():
        return {"ok": False, "error": "not_found", "path": path}

    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return {"ok": False, "error": "old_str_not_found", "path": path}
    if count > 1 and not replace_all:
        return {
            "ok": False,
            "error": "old_str_ambiguous",
            "path": path,
            "count": count,
            "hint": "pass replace_all=true or enlarge unique context",
        }
    if replace_all:
        updated = text.replace(old, new)
        n = count
    else:
        updated = text.replace(old, new, 1)
        n = 1
    p.write_text(updated, encoding="utf-8")
    return {"ok": True, "path": path, "replacements": n, "bytes": len(updated.encode("utf-8"))}


# run allowlist: only python interpreters + unittest entry
_ALLOWED_EXE = {"python", "python3"}


def tool_run_cmd(args: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """
    Run a safe command in workspace cwd.
    Accepts either:
      - argv: ["python3", "test_calc.py"]
      - cmd:  "python3 test_calc.py"  (split, no shell)
    """
    if "argv" in args and args["argv"]:
        argv = [str(x) for x in args["argv"]]
    else:
        cmd = str(_require(args, "cmd")).strip()
        argv = cmd.split()
    if not argv:
        return {"ok": False, "error": "empty_cmd"}

    exe = Path(argv[0]).name
    if exe not in _ALLOWED_EXE:
        return {
            "ok": False,
            "error": "cmd_not_allowed",
            "exe": exe,
            "allowed": sorted(_ALLOWED_EXE),
        }

    timeout = float(args.get("timeout") or 15)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(ws.root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "timeout": timeout, "argv": argv}
    except OSError as e:
        return {"ok": False, "error": "os_error", "detail": str(e), "argv": argv}

    # truncate noisy output
    def _clip(s: str, n: int = 4000) -> str:
        s = s or ""
        return s if len(s) <= n else s[:n] + "\n…[truncated]"

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "argv": argv,
        "stdout": _clip(proc.stdout),
        "stderr": _clip(proc.stderr),
    }


def tool_list_dir(args: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    rel = str(args.get("path") or ".")
    try:
        p = ws.resolve(rel) if rel not in (".", "") else ws.root
    except WorkspaceError as e:
        return {"ok": False, "error": "path_error", "detail": str(e)}
    if not p.is_dir():
        return {"ok": False, "error": "not_a_directory", "path": rel}
    entries = []
    for child in sorted(p.iterdir()):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        entries.append(
            {
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "path": ws.relpath(child),
            }
        )
    return {"ok": True, "path": rel, "entries": entries}


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "list_dir": ToolSpec(
        name="list_dir",
        description="List files under a directory in the workspace",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "relative dir, default ."}},
            "required": [],
        },
        handler=tool_list_dir,
    ),
    "read_file": ToolSpec(
        name="read_file",
        description="Read a text file under the workspace",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "required": ["path"],
        },
        handler=tool_read_file,
    ),
    "search_code": ToolSpec(
        name="search_code",
        description="Search code by substring or regex (agentic, no index)",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "regex": {"type": "boolean"},
                "glob": {"type": "string"},
                "max_hits": {"type": "integer"},
            },
            "required": ["query"],
        },
        handler=tool_search_code,
    ),
    "edit_file": ToolSpec(
        name="edit_file",
        description="Replace old_str with new_str in a file (unique match unless replace_all)",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_str", "new_str"],
        },
        handler=tool_edit_file,
    ),
    "run_cmd": ToolSpec(
        name="run_cmd",
        description="Run allowlisted command (python/python3) in workspace cwd",
        parameters={
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "argv": {"type": "array", "items": {"type": "string"}},
                "timeout": {"type": "number"},
            },
            "required": [],
        },
        handler=tool_run_cmd,
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


def dispatch_tool(name: str, args: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    if name not in TOOL_REGISTRY:
        return {"ok": False, "error": "unknown_tool", "tool": name}
    spec = TOOL_REGISTRY[name]
    errs = validate_args(spec, args or {})
    if errs:
        return {"ok": False, "error": "invalid_args", "detail": errs}
    try:
        return spec.handler(args or {}, ws)
    except Exception as e:  # noqa: BLE001 — surface to agent observation
        return {"ok": False, "error": "handler_exception", "detail": str(e)}
