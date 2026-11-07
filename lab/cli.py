from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

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
    """整批运行：准备实验 → 逐个执行任务 → 汇总资源用量。"""
    settings = Settings.from_env()
    if args.max_total_tokens is not None:
        if args.max_total_tokens < 1:
            raise ValueError("--max-total-tokens must be positive")
        settings.max_total_tokens = args.max_total_tokens
    if args.max_model_calls is not None:
        if args.max_model_calls < 1:
            raise ValueError("--max-model-calls must be positive")
        settings.max_model_calls = args.max_model_calls
    tasks = select_tasks(args.split, args.limit, args.uid, args.subset)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    # Windows 时钟可能让并发进程取得相同时间戳；划分和随机后缀避免目录重合。
    run_dir = RUNS / f"{stamp}-{args.split}-{args.mode}-{uuid4().hex[:8]}"
    # 构造客户端时会检查密钥；无需在 run() 中重复读取，且先于结果文件写入。
    model = DeepSeekModel(settings)
    statuses = []
    try:
        write_json(run_dir / "run.json", {
            "mode": args.mode,
            "split": args.split,
            "subset": "explicit_uid" if args.uid else args.subset,
            "task_ids": [task["uid"] for task in tasks],
            "transport": args.transport,
            "settings": settings.public_dict(),
            "benchmark": read_json(DATA / "manifest.json"),
            "measured": True,
        })
        for task in tasks:
            result = await run_task(task, args, model, settings, run_dir)
            statuses.append(result)
    finally:
        await model.close()

    write_json(run_dir / "metrics_summary.json", {
        "tasks": len(tasks),
        "completed": sum(row["status"] == "completed" for row in statuses),
        "input_tokens": sum(row["input_tokens"] for row in statuses),
        "output_tokens": sum(row["output_tokens"] for row in statuses),
        "model_calls": sum(row["model_calls"] for row in statuses),
        "tool_calls": sum(row["tool_calls"] for row in statuses),
        "grounding_queries": sum(row["grounding_queries"] for row in statuses),
        "runs": statuses,
    })
    print(f"Results: {run_dir}")
    print(f'评分: .venv\\Scripts\\python.exe -m lab.evaluate "{run_dir}"')
    if any(r["status"] == "failed" for r in statuses):
        raise RuntimeError("One or more tasks failed; failures are retained for evaluation")


async def run_task(task, args, model, settings, run_dir):
    """一个任务：连接工具 → solve → 保存计划和指标；失败任务也保留记录。"""
    task_dir = run_dir / task["uid"]
    trace = Trace(task_dir / "trace.jsonl")
    usage = Usage()
    write_json(task_dir / "task.json", task)
    start = time.perf_counter()
    status = "completed"
    failure = None
    root_error_types = []

    try:
        async with connect_tools(args.transport) as tools:
            plan = await solve(task, args.mode, model, tools, settings, usage, trace)
        write_json(task_dir / "plan.json", plan)
    except Exception as exc:
        # 批量评测必须保留失败任务；只记录异常类型，避免泄露请求中的凭据。
        status = "failed"
        failure = type(exc).__name__
        root_error_types = exception_types(exc)
        trace.log("run_failed", error_type=failure, root_error_types=root_error_types)
        print(
            f"{task['uid']}: failed ({failure}); inspect trace.jsonl / model configuration",
            file=sys.stderr,
        )

    metrics = {
        "status": status,
        "error_type": failure,
        "root_error_types": root_error_types,
        "latency_seconds": time.perf_counter() - start,
        **asdict(usage),
    }
    write_json(task_dir / "metrics.json", metrics)
    print(
        f"{task['uid']}: {status}, model_calls={usage.model_calls}, tool_calls={usage.tool_calls}",
        flush=True,
    )
    return {"uid": task["uid"], **metrics}


def exception_types(exc):
    """MCP 上下文会包装异常；只记录内部类型，避免写入可能含凭据的异常正文。"""
    if isinstance(exc, BaseExceptionGroup):
        return sorted({name for child in exc.exceptions for name in exception_types(child)})
    return [type(exc).__name__]


def build_parser():
    """声明命令和参数；这里不执行任何命令。"""
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
    runner.add_argument("--max-total-tokens", type=int, help="可选累计 token 阈值；默认不限制累计用量")
    return parser


def doctor():
    settings = Settings.from_env()
    try:
        api_key()
        configured = True
    except RuntimeError:
        configured = False
    report = {
        "python": sys.version.split()[0],
        "project": str(ROOT),
        "data_ready": (DATA / "manifest.json").exists(),
        "model": settings.model,
        "base_url": settings.base_url,
        "api_key_configured": configured,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


async def show_tools(args):
    async with connect_tools(args.transport) as tools:
        specs = await tools.list_tools()

    if args.name:
        for spec in specs:
            if spec["function"]["name"] == args.name:
                print(json.dumps(spec, ensure_ascii=False, indent=2))
                return
        raise ValueError(f"Unknown tool: {args.name}")
    if args.json:
        print(json.dumps(specs, ensure_ascii=False, indent=2))
        return
    for spec in specs:
        function = spec["function"]
        print(f"{function['name']}: {function['description']}")


async def call_one(args):
    argument_text = (
        args.args_file.read_text(encoding="utf-8-sig")
        if args.args_file else (args.args or "{}")
    )
    payload = json.loads(argument_text)
    if not isinstance(payload, dict):
        raise ValueError("工具参数必须是 JSON 对象")

    async with connect_tools(args.transport) as tools:
        result = await tools.call(args.name, payload)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("success"):
        raise SystemExit(1)


def main():
    """只执行用户选择的一个命令；这些分支不是先后步骤。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()

    if args.command == "doctor":
        doctor()
    elif args.command == "inspect":
        print(json.dumps(load_tasks(args.split)[:args.limit], ensure_ascii=False, indent=2))
    elif args.command == "smoke":
        asyncio.run(smoke())
    elif args.command == "mcp-check":
        from lab.mcp_check import check_mcp
        asyncio.run(check_mcp())
    elif args.command == "tools":
        asyncio.run(show_tools(args))
    elif args.command == "call":
        asyncio.run(call_one(args))
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
