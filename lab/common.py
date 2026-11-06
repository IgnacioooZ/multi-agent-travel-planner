from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "ChinaTravel"
DATA = ROOT / "data"
RUNS = ROOT / "runs"
UPSTREAM_COMMIT = "f445e0011f42594fcc29b8c752ece06ded9a8218"


def use_upstream():
    if not (VENDOR / "agent_env").is_dir():
        raise RuntimeError("ChinaTravel missing. Run: python scripts/bootstrap.py")
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
