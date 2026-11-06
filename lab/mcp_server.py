"""Official MCP Python SDK server wrapping the filtered ChinaTravel tools."""
import asyncio
import contextlib
import json
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool
from lab.tools import DirectTools

server = Server("chinatravel-lab")
backend = DirectTools()
# Preload the full sandbox before AnyIO starts stdio worker threads. Lazy native
# DLL initialization (NumPy/Pandas/etc.) in a callback can hang on Windows.
with contextlib.redirect_stdout(sys.stderr):
    backend.adapter._get_env()


@server.list_tools()
async def list_tools():
    specs = await backend.list_tools()
    return [Tool(name=t["function"]["name"], description=t["function"]["description"], inputSchema=t["function"]["parameters"]) for t in specs]


@server.call_tool()
async def call_tool(name, arguments):
    print(f"MCP call: {name}", file=sys.stderr, flush=True)
    # Upstream libraries sometimes print diagnostics; stdout belongs to MCP.
    with contextlib.redirect_stdout(sys.stderr):
        result = await backend.call(name, arguments or {})
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))],
        structuredContent=result,
        isError=not result.get("success", False),
    )


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
