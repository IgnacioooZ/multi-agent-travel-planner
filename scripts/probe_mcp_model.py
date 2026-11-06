"""真实 DeepSeek ↔ MCP 连通性测试：最多 2 次模型调用、1 次工具调用，有 API 费用。"""
import asyncio
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.agent import Agent, DeepSeekModel, Trace, Usage
from lab.common import RUNS, write_json
from lab.config import Settings, api_key
from lab.tools import connect_tools


async def main():
    api_key()
    settings = replace(Settings.from_env(), max_model_calls=2, max_tool_calls=1, max_output_tokens=512, max_total_tokens=16000)
    directory = RUNS / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-mcp-model-probe")
    trace = Trace(directory / "trace.jsonl")
    usage = Usage()
    model = DeepSeekModel(settings)
    report = {"kind": "paid connectivity probe, NOT benchmark performance", "settings": settings.public_dict(), "status": "FAIL"}
    started = time.perf_counter()
    try:
        async with connect_tools("mcp") as tools:
            agent = Agent("mcp_probe", "你在验证工具链。用户要求上海到杭州的火车信息。必须先调用 intercity_transport_select 一次，start_city=上海，end_city=杭州，intercity_type=train。收到工具结果后只用一两句话概括，不要编造车次。", model, tools, settings, usage, trace, {"intercity_transport_select"})
            result = await agent.run({"request": "请通过工具查询上海到杭州的火车。"}, rounds=2)
        evidence = result["evidence"]
        if not any(e["tool"] == "intercity_transport_select" and e["result"].get("success") for e in evidence):
            raise RuntimeError("Model did not complete a successful MCP query")
        report.update(status="PASS", answer=result["content"], successful_tool_calls=len(evidence))
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["http_status"] = getattr(exc, "status_code", None)
    finally:
        await model.close()
        report["usage"] = asdict(usage)
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(directory / "report.json", report)
    print(f"MCP + model: {report['status']}; model_calls={usage.model_calls}; tool_calls={usage.tool_calls}")
    print(f"Report: {directory / 'report.json'}")
    if report["status"] != "PASS":
        print(f"Error: {report.get('error_type')}, HTTP {report.get('http_status')}")
        raise SystemExit(1)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    asyncio.run(main())
