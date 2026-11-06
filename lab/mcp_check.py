"""真实 MCP 协议验收：启动子进程 → 握手 → 发现 → 调用 → 关闭。无需模型。"""
from __future__ import annotations

import json
import time

from lab.common import RUNS, write_json
from lab.tools import BLOCKED_TOOLS, DirectTools, connect_tools

CASES = [
    ("attractions_select", {"city": "杭州", "key": "price", "op": "le", "value": 100}),
    ("restaurants_select", {"city": "杭州", "key": "price", "op": "ge", "value": 0}),
    ("accommodations_keys", {"city": "杭州"}),
    ("intercity_transport_select", {"start_city": "上海", "end_city": "杭州", "intercity_type": "train"}),
]


async def check_mcp(output=None):
    started = time.perf_counter()
    report = {"kind": "MCP integration acceptance, not model performance", "events": [], "checks": []}
    path = output or RUNS / "mcp-check" / "report.json"

    def record(name, passed, **detail):
        report["checks"].append({"name": name, "passed": bool(passed), **detail})
        print(f"{'PASS' if passed else 'FAIL'}: {name}", flush=True)
        if not passed:
            raise AssertionError(name)

    try:
        async with connect_tools("mcp") as client:
            init = client.initialization
            report["events"].append({"method": "initialize", "result": init.model_dump(mode="json", by_alias=True, exclude_none=True)})
            record("initialize / capabilities", init.capabilities.tools is not None, protocol_version=init.protocolVersion)
            specs = await client.list_tools()
            names = {s["function"]["name"] for s in specs}
            report["events"].append({"method": "tools/list", "tool_names": sorted(names)})
            direct = DirectTools()
            record("工具 schema 与直接调用一致", specs == await direct.list_tools(), tool_count=len(specs))
            record("隐藏标注工具未公开", not names.intersection(BLOCKED_TOOLS))
            for name, arguments in CASES:
                result = await client.call(name, arguments)
                expected = await direct.call(name, arguments)
                report["events"].append({"method": "tools/call", "name": name, "arguments": arguments, "result": result})
                record(name, result.get("success") and result == expected and bool(result.get("data")))

            # Test the actual server boundary, bypassing the client's local blocklist.
            bad_cases = [
                ("attractions_select", {"city": "杭州"}, "缺少必填参数"),
                ("attractions_keys", {"city": 123}, "错误参数类型"),
                ("attractions_select", {"city": "杭州", "key": "price", "op": "not_an_operator", "value": 0}, "非法枚举"),
                ("does_not_exist", {}, "不存在的工具"),
                ("china_travel_load_query", {"split": "easy", "oracle_translation": True}, "服务端拒绝隐藏标注工具"),
            ]
            for name, args, label in bad_cases:
                result = await client.session.call_tool(name, args)
                report["events"].append({"method": "tools/call", "name": name, "arguments": args, "isError": result.isError})
                record(label, result.isError)
            result = await client.call("attractions_keys", {"city": "杭州"})
            record("错误后同一会话仍可继续调用", result.get("success"))
        report["events"].append({"event": "session_closed"})
        report["status"] = "PASS"
    except Exception as exc:
        report["status"] = "FAIL"
        report["error_type"] = type(exc).__name__
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        write_json(path, report)
        print(f"MCP report: {path}", flush=True)
    return report
