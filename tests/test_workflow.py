"""No paid API calls. Test boundaries, accounting, and real role handoffs."""
import asyncio
import json
from dataclasses import replace

import pytest
from lab.agent import Agent, BudgetExceeded, Trace, Usage
from lab.benchmark import load_tasks, select_tasks
from lab.config import Settings
from lab.tools import BLOCKED_TOOLS, DirectTools
from lab.workflow import solve


class FakeTools:
    async def list_tools(self):
        return [{"type": "function", "function": {"name": "attractions_keys", "description": "keys", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}}]

    async def call(self, name, arguments):
        return {"success": True, "data": ["name", "price"]}


class ScriptedModel:
    def __init__(self):
        self.contexts = []
        self.used_tool = False

    async def complete(self, messages, tools, max_tokens):
        self.contexts.append(messages[1]["content"])
        calls = []
        if tools and not self.used_tool:
            self.used_tool = True
            calls = [{"id": "test-call", "type": "function", "function": {"name": "attractions_keys", "arguments": '{"city":"杭州"}'}}]
        if "整合全部候选" in messages[0]["content"]:
            value = {"people_number": 1, "start_city": "上海", "target_city": "杭州", "itinerary": []}
        else:
            value = {"candidates": [], "unresolved": ["scripted test only"]}
        return {"content": json.dumps(value, ensure_ascii=False), "tool_calls": calls, "input_tokens": 10, "output_tokens": 5, "served_model": "test-double", "finish_reason": "stop"}


def test_public_tasks_and_splits():
    tasks = load_tasks()
    assert len(tasks) == 300
    assert all(set(task) == {"uid", "request"} for task in tasks)
    dev = {t["uid"] for t in select_tasks(limit=10)}
    held = {t["uid"] for t in select_tasks(limit=20, subset="holdout")}
    assert len(dev) == 10 and len(held) == 20 and not dev & held


def test_oracle_tools_not_exposed():
    async def check():
        tools = DirectTools()
        names = {t["function"]["name"] for t in await tools.list_tools()}
        assert not names & BLOCKED_TOOLS
        for blocked in BLOCKED_TOOLS:
            assert not (await tools.call(blocked, {"oracle_translation": True}))["success"]
    asyncio.run(check())


def test_multi_agent_handoffs_and_usage(tmp_path):
    model, usage = ScriptedModel(), Usage()
    task = load_tasks()[0]
    plan = asyncio.run(solve(task, "multi", model, FakeTools(), Settings(), usage, Trace(tmp_path / "trace.jsonl")))
    assert isinstance(plan["itinerary"], list)
    assert usage.model_calls == 4 and usage.tool_calls == 1
    assert usage.input_tokens == 40 and usage.output_tokens == 20
    final_context = json.loads(model.contexts[-1])
    assert [b["agent"] for b in final_context["handoffs"]] == ["logistics", "activities"]
    assert "hard_logic_py" not in json.dumps(model.contexts)
    assert final_context["handoffs"][1]["evidence"][0]["tool"] == "attractions_keys"


def test_global_budget_is_not_reset_for_each_agent(tmp_path):
    settings = replace(Settings(), max_model_calls=1)
    with pytest.raises(BudgetExceeded):
        asyncio.run(solve(load_tasks()[0], "multi", ScriptedModel(), FakeTools(), settings, Usage(), Trace(tmp_path / "trace.jsonl")))


def test_bad_tool_arguments_are_returned_to_model(tmp_path):
    class BadArgs(ScriptedModel):
        async def complete(self, messages, tools, max_tokens):
            if self.used_tool:
                assert messages[-1]["role"] == "tool"
                assert json.loads(messages[-1]["content"])["success"] is False
            value = await super().complete(messages, tools, max_tokens)
            if value["tool_calls"]:
                value["tool_calls"][0]["function"]["arguments"] = "not json"
            return value
    usage = Usage()
    result = asyncio.run(Agent("test", "test", BadArgs(), FakeTools(), Settings(), usage, Trace(tmp_path / "trace.jsonl")).run({}, rounds=3))
    assert usage.tool_calls == 0
    assert result["evidence"][0]["result"]["success"] is False
