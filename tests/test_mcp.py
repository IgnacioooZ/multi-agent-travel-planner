import asyncio

from mcp.types import CallToolResult, TextContent

from lab.tools import decode_mcp_result


def test_protocol_error_overrides_success_payload():
    result = CallToolResult(isError=True, structuredContent={"success": True}, content=[TextContent(type="text", text="failed")])
    assert decode_mcp_result(result)["success"] is False


def test_structured_result_is_used_without_text_reparsing():
    result = CallToolResult(isError=False, structuredContent={"success": True, "data": ["杭州"]}, content=[TextContent(type="text", text="human-readable summary")])
    assert decode_mcp_result(result)["data"] == ["杭州"]


def test_plain_text_protocol_error_is_normalized():
    result = CallToolResult(isError=True, content=[TextContent(type="text", text="Input validation error")])
    assert decode_mcp_result(result)["error"] == "Input validation error"


def test_real_mcp_session(tmp_path):
    from lab.mcp_check import check_mcp
    report = asyncio.run(check_mcp(tmp_path / "mcp-report.json"))
    assert report["status"] == "PASS"
    assert all(c["passed"] for c in report["checks"])
