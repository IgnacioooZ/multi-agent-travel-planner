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
    grounding_queries: int = 0
    connection_retries: int = 0


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
        self.client = AsyncOpenAI(
            api_key=api_key(), base_url=settings.base_url,
            timeout=settings.timeout_seconds, max_retries=0,
        )

    async def complete(self, messages, tools, max_tokens):
        if max_tokens is None:
            max_tokens = await self.provider_output_limit()
        args: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            args.update(tools=tools, tool_choice="auto")
            if len(tools)==1 and tools[0]['function']['name']=='finalize_plan':
                args['tool_choice'] = {'type':'function','function':{'name':'finalize_plan'}}
                args['extra_body'] = {'thinking':{'type':'disabled'}}
        import asyncio
        # The SDK's own timeout does not fire when a proxied connection half-opens
        # (VPN drop), so a hung request can block forever. wait_for is the hard cap.
        result = await asyncio.wait_for(
            self.client.chat.completions.create(**args),
            timeout=self.settings.timeout_seconds + 60.0,
        )
        msg = result.choices[0].message
        return {
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in (msg.tool_calls or [])
            ],
            "input_tokens": result.usage.prompt_tokens if result.usage else 0,
            "output_tokens": result.usage.completion_tokens if result.usage else 0,
            "served_model": result.model,
            "finish_reason": result.choices[0].finish_reason,
            "requested_max_tokens": max_tokens,
        }

    async def provider_output_limit(self):
        """Use the advertised service ceiling; omitting max_tokens uses a small default."""
        if not hasattr(self, 'provider_limits'):
            import asyncio
            models = await asyncio.wait_for(self.client.models.list(), timeout=self.settings.timeout_seconds + 60.0)
            model_id = {'deepseek-chat': 'deepseek-flash'}.get(self.settings.model, self.settings.model)
            match = next((m for m in models.data if m.id in (self.settings.model, model_id)), None)
            if match is None or not getattr(match, 'max_output_tokens', None):
                raise RuntimeError('Model service did not advertise an output limit; cannot silently use a default cap')
            self.provider_limits = match.model_dump()
        return self.provider_limits['max_output_tokens']

    async def close(self):
        await self.client.close()


class Agent:
    def __init__(self, name, instructions, model, tools, settings, usage, trace, tool_names=None, validate_output=None):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools
        self.settings = settings
        self.usage = usage
        self.trace = trace
        self.tool_names = tool_names
        self.validate_output = validate_output

    async def run(self, context, rounds):
        """主循环：请求模型 → 提交回答，或执行工具并把结果交回模型。"""
        available = await self.tools.list_tools()
        if self.tool_names is not None:
            available = [t for t in available if t["function"]["name"] in self.tool_names]
        messages = [
            {"role": "system", "content": self.instructions},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
        evidence = []
        corrections = 0

        for step in range(rounds):
            active_tools, max_tokens = self._prepare_request(messages, available, step, rounds)

            # 1. 模型读取历史消息，决定回答或调用工具。
            from openai import APIConnectionError
            try:
                response = await self.model.complete(messages, active_tools, max_tokens)
            except (APIConnectionError, TimeoutError) as exc:
                self.trace.log('model_error', agent=self.name, error_type=type(exc).__name__)
                if self.usage.connection_retries >= 1:
                    raise
                self.usage.connection_retries += 1
                self.trace.log('connection_retry', agent=self.name)
                active_tools, max_tokens = self._prepare_request(messages, available, step, rounds)
                response = await self.model.complete(messages, active_tools, max_tokens)
            self._record_response(messages, response, step)

            # 2. 没有工具调用：结束当前 Agent，交接回答和证据。
            if not response["tool_calls"]:
                errors = self._output_errors(response, context, evidence)
                if self.validate_output is not None and any(t['function']['name']=='finalize_plan' for t in available):
                    errors = ['Use finalize_plan(plan=...) to submit the itinerary; it builds and verifies factual fields.'] + errors
                if errors:
                    self.trace.log("validation_failed", agent=self.name, errors=errors, correction=corrections)
                    if corrections >= 6 or step == rounds - 1:
                        from lab.validation import InvalidPlan
                        raise InvalidPlan("Output validation failed after bounded corrections")
                    corrections += 1
                    messages.append({"role": "user", "content": "提交前检查未通过。请调用 finalize_plan(plan=完整草案) 提交，不要直接输出 JSON；finalize_plan 会按沙盒记录生成真实价格/路线并返回具体 errors 供你修正。当前问题：" + json.dumps(errors, ensure_ascii=False)})
                    continue
                self.trace.log(
                    "handoff", agent=self.name,
                    content=response["content"], evidence_count=len(evidence),
                )
                return {"agent": self.name, "content": response["content"], "evidence": evidence}

            # 3. 有工具调用：逐个执行，把结果放进下一轮的消息历史。
            allowed = {t["function"]["name"] for t in active_tools}
            for call in response["tool_calls"]:
                name = call["function"]["name"]
                args, result = await self._execute_tool(call, allowed, request=context.get('task',{}).get('request',''))
                record = {"tool": name, "arguments": args, "result": result}
                evidence.append(record)
                self.trace.log("tool_result", agent=self.name, **record)
                if name == 'finalize_plan' and result.get('success') and self.validate_output is not None:
                    content = json.dumps(result['plan'], ensure_ascii=False)
                    errors = self.validate_output(content)
                    if not errors:
                        self.trace.log('handoff', agent=self.name, content=content, evidence_count=len(evidence), source='finalize_plan')
                        return {'agent':self.name,'content':content,'evidence':evidence}
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        raise BudgetExceeded(f"{self.name} did not return a final response")

    def _output_errors(self, response, context, evidence):
        if response.get('finish_reason') == 'length':
            return ['Output was truncated. Return complete compact JSON; shorten prose and candidate lists, not required plan fields.']
        if self.validate_output is not None:
            return self.validate_output(response['content'], context=context, evidence=evidence)
        return []

    def _prepare_request(self, messages, available, step, rounds):
        """集中处理共享预算、最后一轮收尾，以及请求计数和日志。"""
        if self.usage.model_calls >= self.settings.max_model_calls:
            raise BudgetExceeded("Model-call budget exhausted")
        used_tokens = self.usage.input_tokens + self.usage.output_tokens
        token_limit = self.settings.max_total_tokens
        if token_limit is not None and used_tokens >= token_limit:
            raise BudgetExceeded("Observed token budget exhausted")
        if self.settings.max_context_chars is not None and len(json.dumps(messages, ensure_ascii=False)) > self.settings.max_context_chars:
            raise BudgetExceeded("Context size limit reached; reduce candidates or improve context selection")

        is_last_round = step == rounds - 1
        tool_budget_exhausted = self.usage.tool_calls >= self.settings.max_tool_calls
        active_tools = [] if is_last_round or tool_budget_exhausted else available
        if is_last_round and not tool_budget_exhausted:
            active_tools = [t for t in available if t['function']['name']=='finalize_plan']
        if self.validate_output is not None and step >= max(0,rounds-6) and not tool_budget_exhausted:
            finalizers = [t for t in available if t['function']['name']=='finalize_plan']
            if finalizers:
                active_tools = finalizers
                messages.append({'role':'user','content':'进入提交阶段。请调用 finalize_plan；根据上次 errors/alternatives 改草案，不再请求研究工具。保留用户要求的天数与预算。'})
        if not active_tools:
            messages.append({
                "role": "user",
                "content": "本阶段工具调用结束。请根据已有证据立即提交最终 JSON，不要请求新工具。",
            })

        self.usage.model_calls += 1
        self.trace.log(
            "model_request", agent=self.name, step=step, messages=messages,
            tools=[t["function"]["name"] for t in active_tools],
        )
        max_tokens = self.settings.max_output_tokens
        if token_limit is not None:
            remaining = token_limit - used_tokens
            max_tokens = remaining if max_tokens is None else min(max_tokens, remaining)
        return active_tools, max_tokens

    def _record_response(self, messages, response, step):
        """保存模型消息，并累计用量；不执行工具。"""
        self.usage.input_tokens += response["input_tokens"]
        self.usage.output_tokens += response["output_tokens"]
        self.trace.log("model_response", agent=self.name, step=step, **response)
        assistant = {"role": "assistant", "content": response["content"]}
        if response["tool_calls"]:
            assistant["tool_calls"] = response["tool_calls"]
        messages.append(assistant)

    async def _execute_tool(self, call, allowed, request=''):
        """校验模型给出的名称和参数；调用错误作为结果返回，让模型有机会纠正。"""
        name = call["function"]["name"]
        if name not in allowed:
            return {}, {"success": False, "error": "Tool not available to this role"}
        # 同一次模型响应可包含多个调用，因此每次执行前仍需检查剩余预算。
        if self.usage.tool_calls >= self.settings.max_tool_calls:
            return {}, {"success": False, "error": "Tool budget exhausted"}

        try:
            args = json.loads(call["function"]["arguments"])
            if not isinstance(args, dict):
                raise ValueError("Arguments must be an object")
        except (ValueError, TypeError) as exc:
            return {}, {"success": False, "error": str(exc)}

        self.usage.tool_calls += 1
        if name == 'finalize_plan':
            args['request'] = request
        result = await self.tools.call(name, args)
        self.usage.grounding_queries += len(result.get('queries', []))
        return args, result


def parse_plan(text):
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Plan must be a JSON object")
    return value
