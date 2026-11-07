import asyncio
import json
import pytest

import httpx
from openai import AsyncOpenAI

from lab.agent import DeepSeekModel
from lab.config import Settings


@pytest.mark.parametrize('requested', [123, None])
@pytest.mark.parametrize('tool_name', ['attractions_keys','finalize_plan'])
def test_deepseek_request_and_usage_without_network(requested, tool_name):
    requests = []

    def respond(request):
        if request.url.path == '/models':
            return httpx.Response(200, json={'object':'list','data':[
                {'id':'deepseek-flash','object':'model','created':0,'owned_by':'deepseek','max_output_tokens':393216}]})
        requests.append(json.loads(request.content))
        assert request.url.path == "/chat/completions"
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "deepseek-chat",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "attractions_keys", "arguments": '{"city":"杭州"}'}}]
            }}], "usage": {"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26}
        })

    async def check():
        model = DeepSeekModel.__new__(DeepSeekModel)
        model.settings = Settings()
        model.client = AsyncOpenAI(api_key="local-test-placeholder", base_url="https://test.invalid", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)), max_retries=0)
        try:
            result = await model.complete([{"role": "user", "content": "test"}], [{"type": "function", "function": {"name": tool_name, "parameters": {"type": "object"}}}], requested)
        finally:
            await model.close()
        assert result["input_tokens"] == 20 and result["output_tokens"] == 6
        assert result["tool_calls"][0]["function"]["name"] == "attractions_keys"
        assert requests[0]["model"] == "deepseek-chat"
        assert requests[0]["max_tokens"] == (123 if requested else 393216)
        assert requests[0]["tool_choice"] == ({'type':'function','function':{'name':'finalize_plan'}} if tool_name=='finalize_plan' else 'auto')
        if tool_name=='finalize_plan':
            assert requests[0]['thinking']=={'type':'disabled'}
    asyncio.run(check())
