"""Run a frozen number of tasks per split, then score each run offline (paid)."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
from uuid import uuid4
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.benchmark import select_tasks
from lab.common import VENDOR, read_json, write_json
from lab.config import Settings, api_key


def run_split(split, count, token_limit, output):
    subset = "dev" if split == "easy" else "all"
    command = [sys.executable, "-u", "-m", "lab.cli", "run", "--mode", "multi",
               "--transport", "mcp", "--split", split, "--subset", subset, "--limit", str(count)]
    if token_limit is not None:
        command.extend(['--max-total-tokens', str(token_limit)])
    env = {**os.environ, "PYTHONUTF8": "1", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
    log = output / f"{split}-run.log"
    print(f"START {split}: {count} tasks", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    directories = [line.removeprefix("Results: ") for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("Results: ")]
    result = {"split": split, "run_exit_code": process.returncode, "command": command}
    if directories:
        run_dir = Path(directories[-1])
        result["run_dir"] = str(run_dir)
        result["metrics"] = read_json(run_dir / "metrics_summary.json")
        with (output / f"{split}-evaluation.log").open("w", encoding="utf-8") as stream:
            scored = subprocess.run([sys.executable, "-u", "-m", "lab.evaluate", str(run_dir)],
                                    cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        result["evaluation_exit_code"] = scored.returncode
        if scored.returncode == 0:
            result["evaluation"] = read_json(run_dir / "evaluation_summary.json")
    write_json(output / f"{split}-result.json", result)
    print(f"DONE {split}: {json.dumps(result.get('evaluation', {'error': 'inspect logs'}))}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counts', nargs=3, type=int, default=[10, 10, 10], metavar=('EASY', 'MEDIUM', 'HUMAN'))
    parser.add_argument('--max-total-tokens', type=int, help='Optional cumulative token cap; omitted means unlimited cumulative usage')
    args = parser.parse_args()
    if any(count < 1 for count in args.counts) or (args.max_total_tokens is not None and args.max_total_tokens < 1):
        parser.error('counts and any specified token cap must be positive')
    counts = dict(zip(('easy', 'medium', 'human'), args.counts))
    settings = Settings.from_env()
    settings.max_total_tokens = args.max_total_tokens
    api_key()
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
    output = ROOT / "runs" / f"{stamp}-pilot{sum(args.counts)}-{uuid4().hex[:8]}"
    manifest = {
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "selection": "first N easy dev; first N medium; first N human; no random sampling",
        "counts": counts,
        "mode": "multi", "transport": "mcp", "settings": settings.public_dict(),
        "task_ids": {split: [t['uid'] for t in select_tasks(split, count, subset='dev' if split == 'easy' else 'all')]
                     for split, count in counts.items()},
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((ROOT / 'lab').glob('*.py'))},
        "benchmark": read_json(ROOT / 'data' / 'manifest.json'),
        "execution": "3 independent split processes; roles and tasks within each process remain sequential",
    }
    # Freeze the exact scoring/data inputs as well as generation code.
    audit_path = ROOT / 'runs/scoring-audit/report.json'
    if audit_path.exists():
        audit = read_json(audit_path)
        manifest['scoring_audit'] = audit
        for name, digest in audit['source_sha256'].items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f'Scorer changed after audit: {name}; rerun verify_scoring.py')
    manifest['data_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for folder in ('public', 'private') for p in sorted((ROOT/'data'/folder).glob('*.json'))}
    write_json(output / 'manifest.json', manifest)
    for path in (ROOT / 'lab').glob('*.py'):
        snapshot = output / 'source' / 'lab' / path.name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, snapshot)
    print(f"PILOT: {output}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run_split, split, count, args.max_total_tokens, output) for split, count in counts.items()]
        results = [future.result() for future in futures]
    manifest['source_run_dirs'] = sorted({r['run_dir'] for r in results if 'run_dir' in r})
    write_json(output / 'manifest.json', manifest)
    write_json(output / 'results.json', {"splits": results})
    print(f"FINISHED: {output}", flush=True)


if __name__ == '__main__':
    main()
