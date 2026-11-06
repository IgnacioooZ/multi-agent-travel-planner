"""真实 MCP + 三角色工作流；脚本化模型，不调用付费 API。"""
import asyncio
import json

from lab.agent import Trace, Usage
from lab.config import Settings
from lab.tools import connect_tools
from lab.workflow import solve


class ModelDouble:
    async def complete(self, messages, tools, max_tokens):
        context = json.loads(messages[1]["content"])
        tool_results = [m for m in messages if m["role"] == "tool"]
        calls = []
        if not tool_results:
            name = next(t["function"]["name"] for t in tools if t["function"]["name"].endswith("_keys"))
            calls = [{"id": "integration-call", "type": "function", "function": {"name": name, "arguments": '{"city":"杭州"}'}}]
        else:
            assert json.loads(tool_results[-1]["content"])["success"]
        payload = {"candidates": [], "unresolved": ["integration test only"]}
        if "output_schema" in context:
            assert [x["agent"] for x in context["handoffs"]] == ["logistics", "activities"]
            assert all(x["evidence"][0]["result"]["success"] for x in context["handoffs"])
            payload = {"people_number": 1, "start_city": "上海", "target_city": "杭州", "itinerary": []}
        return {"content": json.dumps(payload), "tool_calls": calls, "input_tokens": 10, "output_tokens": 5, "served_model": "test-double", "finish_reason": "stop"}


def test_all_roles_use_real_mcp(tmp_path):
    async def check():
        usage = Usage()
        async with connect_tools("mcp") as tools:
            plan = await solve({"uid": "integration-test", "request": "从上海去杭州一日游"}, "multi", ModelDouble(), tools, Settings(), usage, Trace(tmp_path / "trace.jsonl"))
        assert plan["target_city"] == "杭州"
        assert usage.tool_calls == 3 and usage.model_calls == 6
    asyncio.run(check())
