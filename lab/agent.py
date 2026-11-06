"""A small tool-calling agent loop, intentionally independent of agent frameworks."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class Trace:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event, **fields):
        from datetime import datetime, timezone
        row = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


class DeepSeekModel:
    def __init__(self, settings):
        from openai import AsyncOpenAI
        from lab.config import api_key
        self.settings = settings
        # No invisible SDK retries: every call is part of our measured budget.
        self.client = AsyncOpenAI(api_key=api_key(), base_url=settings.base_url, timeout=settings.timeout_seconds, max_retries=0)

    async def complete(self, messages, tools, max_tokens):
        args: dict[str, Any] = dict(model=self.settings.model, messages=messages, temperature=self.settings.temperature, max_tokens=max_tokens)
        if tools:
            args.update(tools=tools, tool_choice="auto")
        result = await self.client.chat.completions.create(**args)
        msg = result.choices[0].message
        return {
            "content": msg.content or "",
            "tool_calls": [{"id": t.id, "type": "function", "function": {"name": t.function.name, "arguments": t.function.arguments}} for t in (msg.tool_calls or [])],
            "input_tokens": result.usage.prompt_tokens if result.usage else 0,
            "output_tokens": result.usage.completion_tokens if result.usage else 0,
            "served_model": result.model,
            "finish_reason": result.choices[0].finish_reason,
        }

    async def close(self):
        await self.client.close()


class Agent:
    def __init__(self, name, instructions, model, tools, settings, usage, trace, tool_names=None):
        self.name, self.instructions = name, instructions
        self.model, self.tools, self.settings = model, tools, settings
        self.usage, self.trace = usage, trace
        self.tool_names = tool_names

    async def run(self, context, rounds):
        available = await self.tools.list_tools()
        if self.tool_names is not None:
            available = [t for t in available if t["function"]["name"] in self.tool_names]
        allowed = {t["function"]["name"] for t in available}
        messages = [{"role": "system", "content": self.instructions}, {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
        evidence = []
        for step in range(rounds):
            if self.usage.model_calls >= self.settings.max_model_calls:
                raise BudgetExceeded("Model-call budget exhausted")
            used_tokens = self.usage.input_tokens + self.usage.output_tokens
            if used_tokens >= self.settings.max_total_tokens:
                raise BudgetExceeded("Observed token budget exhausted")
            if len(json.dumps(messages, ensure_ascii=False)) > self.settings.max_context_chars:
                raise BudgetExceeded("Context size limit reached; reduce candidates or improve context selection")
            # Reserve the last stage call for a final response instead of another tool call.
            active_tools = available if step < rounds - 1 and self.usage.tool_calls < self.settings.max_tool_calls else []
            if not active_tools:
                messages.append({"role": "user", "content": "本阶段工具调用结束。请根据已有证据立即提交最终 JSON，不要请求新工具。"})
            self.usage.model_calls += 1
            self.trace.log("model_request", agent=self.name, step=step, messages=messages, tools=[t["function"]["name"] for t in active_tools])
            response = await self.model.complete(messages, active_tools, min(self.settings.max_output_tokens, self.settings.max_total_tokens - used_tokens))
            self.usage.input_tokens += response["input_tokens"]
            self.usage.output_tokens += response["output_tokens"]
            self.trace.log("model_response", agent=self.name, step=step, **response)
            assistant = {"role": "assistant", "content": response["content"]}
            if response["tool_calls"]:
                assistant["tool_calls"] = response["tool_calls"]
            messages.append(assistant)
            if not response["tool_calls"]:
                self.trace.log("handoff", agent=self.name, content=response["content"], evidence_count=len(evidence))
                return {"agent": self.name, "content": response["content"], "evidence": evidence}
            for call in response["tool_calls"]:
                name = call["function"]["name"]
                if name not in allowed or not active_tools:
                    result = {"success": False, "error": "Tool not available to this role"}
                    args = {}
                elif self.usage.tool_calls >= self.settings.max_tool_calls:
                    result = {"success": False, "error": "Tool budget exhausted"}
                    args = {}
                else:
                    try:
                        args = json.loads(call["function"]["arguments"])
                        if not isinstance(args, dict):
                            raise ValueError("Arguments must be an object")
                    except (ValueError, TypeError) as exc:
                        args, result = {}, {"success": False, "error": str(exc)}
                    else:
                        self.usage.tool_calls += 1
                        result = await self.tools.call(name, args)
                record = {"tool": name, "arguments": args, "result": result}
                evidence.append(record)
                self.trace.log("tool_result", agent=self.name, **record)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False, default=str)})
        raise BudgetExceeded(f"{self.name} did not return a final response")


def parse_plan(text):
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Plan must be a JSON object")
    return value
