"""Read-only official sandbox tools, with no query/oracle/file/shell access."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from contextlib import asynccontextmanager

from lab.common import ROOT, use_upstream

BLOCKED_TOOLS = {"china_travel_load_query", "china_travel_list_splits", "china_travel_world_command"}


class DirectTools:
    def __init__(self):
        use_upstream()
        from agent_env.adapter import ChinaTravelEnvAdapter
        self.adapter = ChinaTravelEnvAdapter(lang="zh")

    async def list_tools(self):
        return [t for t in self.adapter.list_tools("openai") if t["function"]["name"] not in BLOCKED_TOOLS]

    async def call(self, name, arguments):
        if name in BLOCKED_TOOLS:
            return {"success": False, "error": "Tool is not exposed to benchmark agents"}
        return self.adapter.call_tool(name, arguments)


class MCPTools:
    def __init__(self, session, initialization=None):
        self.session = session
        self.initialization = initialization

    async def list_tools(self):
        result = await self.session.list_tools()
        return [{"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": t.inputSchema}} for t in result.tools if t.name not in BLOCKED_TOOLS]

    async def call(self, name, arguments):
        if name in BLOCKED_TOOLS:
            return {"success": False, "error": "Tool is not exposed to benchmark agents"}
        result = await self.session.call_tool(name, arguments)
        return decode_mcp_result(result)


def decode_mcp_result(result):
    """MCP 协议结果 → Agent 使用的业务字典；协议错误不能被误当成功。"""
    text = "\n".join(part.text for part in result.content if part.type == "text")
    payload = result.structuredContent
    if payload is None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"text": text}
    if not isinstance(payload, dict):
        payload = {"data": payload}
    payload = dict(payload)
    payload.setdefault("success", not result.isError)
    if result.isError:
        payload["success"] = False
        payload.setdefault("error", text or "MCP tool execution failed")
    return payload


@asynccontextmanager
async def connect_tools(transport="direct"):
    if transport not in {"direct", "mcp"}:
        raise ValueError(f"Unknown transport: {transport}")
    if transport == "direct":
        yield DirectTools()
        return
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=["-u", "-m", "lab.mcp_server"], cwd=str(ROOT), env={"PYTHONUTF8": "1", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=90)) as session:
            initialization = await session.initialize()
            yield MCPTools(session, initialization)
