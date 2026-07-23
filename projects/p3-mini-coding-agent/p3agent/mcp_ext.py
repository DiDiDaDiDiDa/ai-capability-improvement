"""
M5 · MCP 工具扩展（教学最小版）—— 证明「注册表可被外部动态扩展」。

真实 MCP：agent 作为 client 连到外部 MCP server（stdio/SSE），server 声明一批
tool（name + JSON Schema），client 把它们注册进自己的工具表，调用时转发给 server。

这里不起真进程，用一个内存里的「MCP server」模拟它 list_tools / call_tool 两个动作，
再把它 register 进 P3 的 TOOL_REGISTRY —— 关键在于：**核心 loop 一行不改，
新能力靠往注册表加 ToolSpec 就接上了**（Claude Code 的 MCP/Skills 扩展范式）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .tools import TOOL_REGISTRY, ToolSpec
from .workspace import Workspace


@dataclass
class MCPTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]  # MCP 侧不吃 Workspace


class MockMCPServer:
    """内存 MCP server：声明工具 + 执行工具。模拟 stdio/SSE server 的两个核心动作。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self._tools: dict[str, MCPTool] = {}

    def add_tool(self, tool: MCPTool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in self._tools.values()]

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            return {"ok": False, "error": "mcp_unknown_tool", "tool": name}
        return self._tools[name].handler(args)


def register_mcp_server(server: MockMCPServer, prefix: str | None = None) -> list[str]:
    """把 MCP server 声明的工具注册进 P3 TOOL_REGISTRY。返回注册的工具名列表。

    prefix 命名空间隔离（真实 MCP 也会用 server 名做前缀防冲突）。
    handler 适配：P3 handler 签名是 (args, ws)，这里丢掉 ws 转发给 MCP。
    """
    registered: list[str] = []
    for meta in server.list_tools():
        tool_name = f"{prefix}.{meta['name']}" if prefix else meta["name"]

        def make_handler(mcp_name: str) -> Callable[[dict[str, Any], Workspace], dict[str, Any]]:
            def _handler(args: dict[str, Any], ws: Workspace) -> dict[str, Any]:
                return server.call_tool(mcp_name, args)  # 转发到 MCP server
            return _handler

        TOOL_REGISTRY[tool_name] = ToolSpec(
            name=tool_name,
            description=f"[MCP:{server.name}] {meta['description']}",
            parameters=meta["parameters"],
            handler=make_handler(meta["name"]),
        )
        registered.append(tool_name)
    return registered


def build_demo_mcp_server() -> MockMCPServer:
    """一个玩具 MCP server：提供 word_count 工具（外部能力的占位）。"""
    server = MockMCPServer(name="demo")

    def word_count(args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text") or "")
        return {"ok": True, "words": len(text.split()), "chars": len(text)}

    server.add_tool(MCPTool(
        name="word_count",
        description="Count words/chars in text (external tool via MCP)",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=word_count,
    ))
    return server
