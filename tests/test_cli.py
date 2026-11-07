"""批量任务失败必须留档、继续下一条任务，最终关闭客户端。"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from lab import cli
from lab.common import read_json
from lab.config import Settings


def test_batch_retains_failures_and_closes_resources(tmp_path, monkeypatch):
    tasks = [{"uid": "bad", "request": "first"}, {"uid": "good", "request": "second"}]
    events = []

    class Model:
        async def close(self):
            events.append("model_closed")

    @asynccontextmanager
    async def connected(transport):
        events.append("connected")
        try:
            yield object()
        finally:
            events.append("disconnected")

    async def solve(task, mode, model, tools, settings, usage, trace):
        usage.model_calls += 1
        if task["uid"] == "bad":
            raise ExceptionGroup("MCP wrapper", [ValueError("sensitive request details must not be written")])
        return {"itinerary": []}

    monkeypatch.setattr(cli, "RUNS", tmp_path)
    monkeypatch.setattr(cli, "select_tasks", lambda *args: tasks)
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings())
    monkeypatch.setattr(cli, "DeepSeekModel", lambda settings: Model())
    monkeypatch.setattr(cli, "connect_tools", connected)
    monkeypatch.setattr(cli, "solve", solve)
    args = cli.build_parser().parse_args(["run", "--limit", "2"])

    with pytest.raises(RuntimeError, match="One or more tasks failed"):
        asyncio.run(cli.run(args))
    run_dir = next(tmp_path.iterdir())
    summary = read_json(run_dir / "metrics_summary.json")
    assert summary["tasks"] == 2 and summary["completed"] == 1
    assert summary["model_calls"] == 2
    assert [row["status"] for row in summary["runs"]] == ["failed", "completed"]
    assert summary["runs"][0]["root_error_types"] == ["ValueError"]
    assert summary["runs"][1]["root_error_types"] == []
    assert not (run_dir / "bad" / "plan.json").exists()
    assert read_json(run_dir / "good" / "plan.json") == {"itinerary": []}
    assert "sensitive request" not in (run_dir / "bad" / "trace.jsonl").read_text()
    assert events == ["connected", "disconnected", "connected", "disconnected", "model_closed"]


def test_missing_key_leaves_no_run_directory(tmp_path, monkeypatch):
    def missing_key():
        raise RuntimeError("Missing key")

    monkeypatch.setattr(cli, "RUNS", tmp_path)
    monkeypatch.setattr(cli, "select_tasks", lambda *args: [{"uid": "test", "request": "test"}])
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings())
    monkeypatch.setattr("lab.config.api_key", missing_key)
    args = cli.build_parser().parse_args(["run"])
    with pytest.raises(RuntimeError, match="Missing key"):
        asyncio.run(cli.run(args))
    assert list(tmp_path.iterdir()) == []


def test_same_timestamp_runs_get_distinct_directories(tmp_path, monkeypatch):
    from datetime import datetime

    class FrozenClock:
        @staticmethod
        def now():
            return datetime(2026, 11, 7, 16, 0, 0)

    class Model:
        async def close(self):
            pass

    async def run_task(task, args, model, settings, run_dir):
        return {"uid": task["uid"], "status": "completed", "model_calls": 0,
                "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "grounding_queries": 0}

    monkeypatch.setattr(cli, "RUNS", tmp_path)
    monkeypatch.setattr(cli, "datetime", FrozenClock)
    monkeypatch.setattr(cli, "select_tasks", lambda *args: [{"uid": "same", "request": "test"}])
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings())
    monkeypatch.setattr(cli, "DeepSeekModel", lambda settings: Model())
    monkeypatch.setattr(cli, "run_task", run_task)
    args = cli.build_parser().parse_args(["run"])
    asyncio.run(cli.run(args))
    asyncio.run(cli.run(args))
    directories = list(tmp_path.iterdir())
    assert len(directories) == 2
    assert all((p / "metrics_summary.json").exists() for p in directories)
