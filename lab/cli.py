from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from dataclasses import asdict
from datetime import datetime

from lab.agent import DeepSeekModel, Trace, Usage
from lab.benchmark import load_tasks, select_tasks
from lab.common import DATA, ROOT, RUNS, read_json, write_json
from lab.config import Settings, api_key
from lab.tools import connect_tools
from lab.workflow import solve


async def smoke():
    """Integration checks with real benchmark data/tools, no model or API key."""
    manifest = read_json(DATA / "manifest.json")
    report = {"kind": "infrastructure_smoke_test_NOT_agent_performance", "task_counts": manifest["task_counts"], "transports": {}}
    for transport in ("direct", "mcp"):
        print(f"Checking {transport} tools...", file=sys.stderr, flush=True)
        async with connect_tools(transport) as tools:
            specs = await tools.list_tools()
            result = await tools.call("attractions_keys", {"city": "杭州"})
            if not result.get("success"):
                raise RuntimeError(f"{transport} failed: {result}")
            attractions = await tools.call("attractions_select", {"city": "杭州", "key": "price", "op": "le", "value": 100})
            trains = await tools.call("intercity_transport_select", {"start_city": "上海", "end_city": "杭州", "intercity_type": "train"})
            for value in (attractions, trains):
                if not value.get("success") or not value.get("data", {}).get("rows"):
                    raise RuntimeError(f"{transport} returned no expected sandbox records: {value}")
            report["transports"][transport] = {"tool_count": len(specs), "query_success": True, "sample": result, "attractions": attractions, "trains": trains}
    if report["transports"]["direct"]["attractions"] != report["transports"]["mcp"]["attractions"]:
        raise AssertionError("Direct and MCP tool results differ")
    from lab.evaluate import evaluate_plan
    print("Checking official scorer...", file=sys.stderr, flush=True)
    task = load_tasks()[0]
    # Deliberately invalid output must fail. This does not measure model quality.
    rejected = evaluate_plan("easy", task["uid"], {})
    if rejected["all_pass"] or rejected["schema_pass"]:
        raise AssertionError("Invalid plan was unexpectedly accepted")
    report["scorer_rejects_invalid_plan"] = True
    write_json(RUNS / "smoke" / "report.json", report)
    print(json.dumps({"status": "PASS", "task_counts": report["task_counts"], "tool_counts": {k: v["tool_count"] for k, v in report["transports"].items()}, "scorer_rejects_invalid_plan": True, "report": str(RUNS / "smoke" / "report.json")}, ensure_ascii=False, indent=2))


async def run(args):
    settings = Settings.from_env()
    if args.max_model_calls is not None:
        if args.max_model_calls < 1:
            raise ValueError("--max-model-calls must be positive")
        settings.max_model_calls = args.max_model_calls
    api_key()  # Fail before creating incomplete result folders if no key is configured.
    tasks = select_tasks(args.split, args.limit, args.uid, args.subset)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = RUNS / f"{stamp}-{args.mode}"
    write_json(run_dir / "run.json", {"mode": args.mode, "split": args.split, "subset": args.subset if not args.uid else "explicit_uid", "task_ids": [t["uid"] for t in tasks], "transport": args.transport, "settings": settings.public_dict(), "benchmark": read_json(DATA / "manifest.json"), "measured": True})
    model = DeepSeekModel(settings)
    statuses = []
    try:
        for task in tasks:
            task_dir = run_dir / task["uid"]
            trace = Trace(task_dir / "trace.jsonl")
            usage = Usage()
            write_json(task_dir / "task.json", task)
            start = time.perf_counter()
            status = "completed"
            failure = None
            try:
                async with connect_tools(args.transport) as tools:
                    plan = await solve(task, args.mode, model, tools, settings, usage, trace)
                write_json(task_dir / "plan.json", plan)
            except Exception as exc:
                # Never dump request headers or credentials into an error report.
                status, failure = "failed", type(exc).__name__
                trace.log("run_failed", error_type=failure)
                print(f"{task['uid']}: failed ({failure}); inspect trace.jsonl / model configuration", file=sys.stderr)
            metrics = {"status": status, "error_type": failure, "latency_seconds": time.perf_counter() - start, **asdict(usage)}
            write_json(task_dir / "metrics.json", metrics)
            statuses.append({"uid": task["uid"], **metrics})
            print(f"{task['uid']}: {status}, model_calls={usage.model_calls}, tool_calls={usage.tool_calls}", flush=True)
    finally:
        await model.close()
    write_json(run_dir / "metrics_summary.json", {"tasks": len(tasks), "completed": sum(r["status"] == "completed" for r in statuses), "input_tokens": sum(r["input_tokens"] for r in statuses), "output_tokens": sum(r["output_tokens"] for r in statuses), "model_calls": sum(r["model_calls"] for r in statuses), "tool_calls": sum(r["tool_calls"] for r in statuses), "runs": statuses})
    print(f"Results: {run_dir}")
    print(f'评分: .venv\\Scripts\\python.exe -m lab.evaluate "{run_dir}"')
    if any(r["status"] == "failed" for r in statuses):
        raise RuntimeError("One or more tasks failed; failures are retained for evaluation")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ChinaTravel 学习项目：数据、工具、单/多智能体与评测")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查环境和密钥是否存在（不显示密钥）")
    sub.add_parser("smoke", help="真实数据、direct/MCP 工具和评分器自检，无模型费用")
    sub.add_parser("mcp-check", help="独立 MCP 握手、发现、调用、错误处理验收，无需模型")
    inspect = sub.add_parser("inspect", help="只显示 Agent 可见的任务")
    inspect.add_argument("--split", choices=["easy", "medium", "human"], default="easy")
    inspect.add_argument("--limit", type=int, default=1)
    listing = sub.add_parser("tools", help="列出 Agent 可用工具")
    listing.add_argument("--transport", choices=["direct", "mcp"], default="mcp")
    listing.add_argument("--name", help="查看一个工具的完整 JSON schema")
    listing.add_argument("--json", action="store_true", help="输出所有工具的完整 JSON 定义")
    caller = sub.add_parser("call", help="手动调用一个工具，无需模型")
    caller.add_argument("name", help="tools 命令列出的工具名称")
    caller.add_argument("--transport", choices=["direct", "mcp"], default="mcp")
    arguments = caller.add_mutually_exclusive_group()
    arguments.add_argument("--args", default=None, help="JSON 对象（PowerShell 建议用 --args-file）")
    arguments.add_argument("--args-file", type=Path, help="UTF-8 JSON 参数文件路径")
    runner = sub.add_parser("run", help="使用 DeepSeek 运行真实任务，会产生 API 费用")
    runner.add_argument("--mode", choices=["single", "multi"], default="multi")
    runner.add_argument("--transport", choices=["direct", "mcp"], default="mcp")
    runner.add_argument("--split", choices=["easy", "medium", "human"], default="easy")
    runner.add_argument("--subset", choices=["dev", "holdout", "all"], default="dev")
    runner.add_argument("--limit", type=int, default=1)
    runner.add_argument("--uid")
    runner.add_argument("--max-model-calls", type=int)
    args = parser.parse_args()
    if args.command == "doctor":
        settings = Settings.from_env()
        try:
            api_key()
            configured = True
        except RuntimeError:
            configured = False
        print(json.dumps({"python": sys.version.split()[0], "project": str(ROOT), "data_ready": (DATA / "manifest.json").exists(), "model": settings.model, "base_url": settings.base_url, "api_key_configured": configured}, ensure_ascii=False, indent=2))
    elif args.command == "inspect":
        print(json.dumps(load_tasks(args.split)[:args.limit], ensure_ascii=False, indent=2))
    elif args.command == "smoke":
        asyncio.run(smoke())
    elif args.command == "mcp-check":
        from lab.mcp_check import check_mcp
        asyncio.run(check_mcp())
    elif args.command == "tools":
        async def show_tools():
            async with connect_tools(args.transport) as tools:
                specs = await tools.list_tools()
                if args.name:
                    selected = [t for t in specs if t["function"]["name"] == args.name]
                    if not selected:
                        raise ValueError(f"Unknown tool: {args.name}")
                    print(json.dumps(selected[0], ensure_ascii=False, indent=2))
                    return
                if args.json:
                    print(json.dumps(specs, ensure_ascii=False, indent=2))
                    return
                for spec in specs:
                    f = spec["function"]
                    print(f"{f['name']}: {f['description']}")
        asyncio.run(show_tools())
    elif args.command == "call":
        payload = json.loads(args.args_file.read_text(encoding="utf-8-sig") if args.args_file else (args.args or "{}"))
        if not isinstance(payload, dict):
            raise ValueError("工具参数必须是 JSON 对象")
        async def call_one():
            async with connect_tools(args.transport) as tools:
                result = await tools.call(args.name, payload)
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                return result
        if not asyncio.run(call_one()).get("success"):
            raise SystemExit(1)
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
