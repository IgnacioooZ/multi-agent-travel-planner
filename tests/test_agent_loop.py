"""重构回归：多次调用的消息顺序、权限和共享预算；不访问模型 API。"""
import asyncio
import json
from dataclasses import replace

import pytest

from lab.agent import Agent, BudgetExceeded, Trace, Usage
from lab.config import Settings


class RecordingTools:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [{
            "type": "function",
            "function": {
                "name": "lookup", "description": "query a city",
                "parameters": {"type": "object"},
            },
        }]

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return {"success": True, "data": arguments}


def tool_call(call_id, name="lookup", arguments='{"city":"杭州"}'):
    return {
        "id": call_id, "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class SequenceModel:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.requests = []

    async def complete(self, messages, tools, max_tokens):
        # 复制快照，后续 messages.append 不应改变先前请求的记录。
        self.requests.append(json.loads(json.dumps({"messages": messages, "tools": tools})))
        calls = next(self.batches)
        return {
            "content": "" if calls else '{"answer":"done"}',
            "tool_calls": calls, "input_tokens": 10, "output_tokens": 5,
        }


def execute(tmp_path, model, tools, settings=None, rounds=4):
    usage = Usage()
    agent = Agent(
        "test", "test", model, tools, settings or Settings(), usage,
        Trace(tmp_path / "trace.jsonl"),
    )
    result = asyncio.run(agent.run({"request": "query cities"}, rounds=rounds))
    return result, usage


def test_multiple_calls_are_returned_before_next_model_round(tmp_path):
    model = SequenceModel([
        [tool_call("a"), tool_call("b", arguments='{"city":"上海"}')],
        [tool_call("c")],
        [],
    ])
    tools = RecordingTools()
    result, usage = execute(tmp_path, model, tools)
    assert usage.model_calls == 3 and usage.tool_calls == 3
    assert (usage.input_tokens, usage.output_tokens) == (30, 15)
    assert len(result["evidence"]) == 3
    second_messages = model.requests[1]["messages"]
    assert [m["role"] for m in second_messages] == ["system", "user", "assistant", "tool", "tool"]
    assert [c["id"] for c in second_messages[2]["tool_calls"]] == ["a", "b"]
    assert [m["tool_call_id"] for m in second_messages[3:]] == ["a", "b"]
    assert json.loads(second_messages[-1]["content"])["data"]["city"] == "上海"
    assert model.requests[2]["messages"][-1]["tool_call_id"] == "c"


@pytest.mark.parametrize("call", [
    tool_call("forbidden", name="hidden_tool"),
    tool_call("bad-shape", arguments="[]"),
])
def test_rejected_call_is_feedback_not_execution(tmp_path, call):
    model = SequenceModel([[call], []])
    tools = RecordingTools()
    result, usage = execute(tmp_path, model, tools)
    assert tools.calls == [] and usage.tool_calls == 0
    feedback = model.requests[1]["messages"][-1]
    assert feedback["tool_call_id"] == call["id"]
    assert json.loads(feedback["content"])["success"] is False
    assert result["evidence"][0]["result"]["success"] is False


def test_budget_exhausted_between_calls_in_same_response(tmp_path):
    model = SequenceModel([[tool_call("a"), tool_call("b")], []])
    tools = RecordingTools()
    result, usage = execute(tmp_path, model, tools, replace(Settings(), max_tool_calls=1))
    assert len(tools.calls) == usage.tool_calls == 1
    assert result["evidence"][0]["result"]["success"] is True
    assert result["evidence"][1]["result"]["error"] == "Tool budget exhausted"
    assert model.requests[1]["tools"] == []


def test_last_round_withholds_tools_and_can_return_answer(tmp_path):
    model = SequenceModel([[tool_call("a")], []])
    result, usage = execute(tmp_path, model, RecordingTools(), rounds=2)
    assert model.requests[0]["tools"]
    assert model.requests[1]["tools"] == []
    assert result["content"] == '{"answer":"done"}'
    assert usage.model_calls == 2


def test_model_cannot_execute_tool_in_final_round(tmp_path):
    model = SequenceModel([[tool_call("unexpected")]])
    tools = RecordingTools()
    with pytest.raises(BudgetExceeded, match="did not return"):
        execute(tmp_path, model, tools, rounds=1)
    assert model.requests[0]["tools"] == []
    assert tools.calls == []


@pytest.mark.parametrize("limit", ["max_model_calls", "max_total_tokens", "max_context_chars"])
def test_exhausted_budget_prevents_model_request(tmp_path, limit):
    model = SequenceModel([[]])
    with pytest.raises(BudgetExceeded):
        execute(tmp_path, model, RecordingTools(), replace(Settings(), **{limit: 0}))
    assert model.requests == []


def test_no_token_cap_continues_above_old_threshold_and_records_usage(tmp_path):
    class Model(SequenceModel):
        async def complete(self, messages, tools, max_tokens):
            assert max_tokens is None
            return await super().complete(messages, tools, max_tokens)

    usage = Usage(input_tokens=150000, output_tokens=10000)
    model = Model([[]])
    agent = Agent("test", "test", model, RecordingTools(), Settings(), usage,
                  Trace(tmp_path / "trace.jsonl"))
    result = asyncio.run(agent.run({}, rounds=1))
    assert result['content'] == '{"answer":"done"}'
    assert usage.input_tokens == 150010 and usage.output_tokens == 10005


def test_default_does_not_block_large_context(tmp_path):
    model = SequenceModel([[]])
    usage = Usage()
    agent = Agent('test', 'test', model, RecordingTools(), Settings(), usage, Trace(tmp_path/'trace.jsonl'))
    asyncio.run(agent.run({'text': 'x' * 200000}, rounds=1))
    assert usage.model_calls == 1


def test_connection_retry_is_explicit_and_counted(tmp_path):
    import httpx
    from openai import APIConnectionError
    class Model(SequenceModel):
        attempts=0
        async def complete(self, messages, tools, max_tokens):
            self.attempts += 1
            if self.attempts == 1:
                raise APIConnectionError(request=httpx.Request('POST','https://test.invalid'))
            return await super().complete(messages,tools,max_tokens)
    model=Model([[]])
    result,usage=execute(tmp_path,model,RecordingTools())
    assert usage.model_calls == 2 and usage.connection_retries == 1
    assert usage.input_tokens == 10
    events=[json.loads(s) for s in (tmp_path/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert sum(e['event']=='model_request' for e in events)==2
    assert sum(e['event']=='connection_retry' for e in events)==1
