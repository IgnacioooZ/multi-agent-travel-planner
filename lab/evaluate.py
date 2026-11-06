"""Offline scoring only. This module is never imported by the solving workflow."""
from __future__ import annotations

import argparse
import contextlib
import os
from pathlib import Path

from lab.common import DATA, VENDOR, read_json, write_json, use_upstream


def evaluate_plan(split, uid, plan):
    if split not in {"easy", "medium", "human"}:
        raise ValueError("Unknown source split")
    query = next((q for q in read_json(DATA / "private" / f"{split}.json") if q["uid"] == uid), None)
    if query is None:
        raise ValueError(f"Unknown query: {uid}")
    if not query.get("hard_logic_py"):
        raise ValueError("Missing evaluation annotations; cannot report a hard-constraint pass")
    use_upstream()
    from agent_env.scripts.solve_script_with_harness import evaluate_one
    # Some upstream modules use repository-relative resources.
    with contextlib.chdir(VENDOR):
        return evaluate_one(split, uid, query, plan, "zh")


def score_run(run_dir):
    run_dir = Path(run_dir).resolve()
    config = read_json(run_dir / "run.json")
    results = []
    for uid in config["task_ids"]:
        task_dir = run_dir / uid
        plan_file = task_dir / "plan.json"
        if not plan_file.exists():
            score = {"uid": uid, "all_pass": False, "schema_pass": False, "commonsense_pass": False, "logical_pass": False, "reason": "No final plan (run failed or output invalid)"}
        else:
            score = evaluate_plan(config["split"], uid, read_json(plan_file))
        write_json(task_dir / "evaluation.json", score)
        results.append(score)
    # Missing outputs remain in the denominator. Evaluator exceptions propagate.
    summary = {"tasks": len(results), "all_pass_count": sum(bool(r["all_pass"]) for r in results), "complete_success_rate": sum(bool(r["all_pass"]) for r in results) / len(results), "mode": config["mode"], "split": config["split"], "subset": config["subset"], "note": "Local subset, official per-task evaluators; preference metrics not included in this starter."}
    write_json(run_dir / "evaluation_summary.json", summary)
    return summary


def main():
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="调用官方 ChinaTravel 评分器，不发起模型请求")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    import json
    print(json.dumps(score_run(args.run_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
