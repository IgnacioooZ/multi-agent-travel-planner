"""Download pinned official code, Chinese sandbox and tasks; no model API calls."""
from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.common import DATA, ROOT, VENDOR, UPSTREAM_COMMIT, read_json, write_json


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ChinaTravel-Learning-Lab/0.1"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def decode_cell(value):
    if value is None or value == "":
        return value
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def main():
    VENDOR.parent.mkdir(parents=True, exist_ok=True)
    if not VENDOR.exists():
        subprocess.run(["git", "clone", "https://github.com/LAMDA-NeSy/ChinaTravel.git", str(VENDOR)], check=True)
    actual = subprocess.check_output(["git", "-C", str(VENDOR), "rev-parse", "HEAD"], text=True).strip()
    if actual != UPSTREAM_COMMIT:
        # Do not discard any modifications made by the learner.
        dirty = subprocess.check_output(["git", "-C", str(VENDOR), "status", "--porcelain"], text=True)
        if dirty.strip():
            raise RuntimeError("Upstream checkout has changes; pin the version manually without discarding your work.")
        subprocess.run(["git", "-C", str(VENDOR), "fetch", "origin", UPSTREAM_COMMIT], check=True)
        subprocess.run(["git", "-C", str(VENDOR), "checkout", "--detach", UPSTREAM_COMMIT], check=True)

    manifest_path = DATA / "manifest.json"
    lock_path = ROOT / "benchmark.lock.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else (read_json(lock_path) if lock_path.exists() else {"code_commit": UPSTREAM_COMMIT, "sources": {}})
    source_files = {
        "LAMDA-NeSy/ChinaTravel-Sandbox": ["raw/ChinaTravel_sandbox_zh.zip"],
        "LAMDA-NeSy/ChinaTravel": ["easy.csv", "medium.csv", "human.csv"],
    }
    for repo, filenames in source_files.items():
        entry = manifest["sources"].get(repo)
        if entry is None:
            meta = json.loads(fetch(f"https://huggingface.co/api/datasets/{repo}"))
            entry = {"revision": meta["sha"], "files": {}}
            manifest["sources"][repo] = entry
            write_json(manifest_path, manifest)
        for name in filenames:
            dest = DATA / "downloads" / Path(name).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                print(f"Downloading {repo}/{name}", flush=True)
                payload = fetch(f"https://huggingface.co/datasets/{repo}/resolve/{entry['revision']}/{name}")
                dest.write_bytes(payload)
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            expected = entry["files"].get(name, {}).get("sha256")
            if expected and digest != expected:
                raise RuntimeError(f"Checksum mismatch: {dest}")
            entry["files"][name] = {"sha256": digest, "bytes": dest.stat().st_size}
            write_json(manifest_path, manifest)

    database = VENDOR / "chinatravel" / "environment" / "database"
    extraction = DATA / "sandbox_extract"
    if not database.exists():
        extraction.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(DATA / "downloads" / "ChinaTravel_sandbox_zh.zip") as archive:
            root = extraction.resolve()
            for member in archive.infolist():
                if not (root / member.filename).resolve().is_relative_to(root):
                    raise ValueError("Archive contains a path outside its destination")
            archive.extractall(extraction)
        candidates = [p for p in extraction.rglob("attractions") if p.is_dir() and (p.parent / "restaurants").is_dir()]
        if len(candidates) != 1:
            raise RuntimeError(f"Cannot locate sandbox root: {candidates}")
        shutil.copytree(candidates[0].parent, database)

    counts = {}
    for split in ("easy", "medium", "human"):
        raw = (DATA / "downloads" / f"{split}.csv").read_text(encoding="utf-8-sig")
        rows = [{k: decode_cell(v) for k, v in row.items()} for row in csv.DictReader(io.StringIO(raw))]
        for row in rows:
            if not isinstance(row.get("hard_logic_py"), list):
                raise ValueError(f"Invalid oracle field in {row.get('uid')}")
        write_json(DATA / "private" / f"{split}.json", rows)
        # Allowlist: neither hidden constraints nor reference solutions reach an Agent.
        public = [{"uid": r["uid"], "request": r["nature_language"]} for r in rows]
        write_json(DATA / "public" / f"{split}.json", public)
        counts[split] = len(rows)
    if not (DATA / "splits.json").exists():
        write_json(DATA / "splits.json", {
            "note": "Local learning splits, not an official leaderboard split. Freeze before experiments.",
            "dev": [r["uid"] for r in read_json(DATA / "public" / "easy.json")[:10]],
            "holdout": [r["uid"] for r in read_json(DATA / "public" / "easy.json")[10:30]],
        })
    manifest["task_counts"] = counts
    manifest["sandbox_csv_count"] = len(list(database.rglob("*.csv")))
    write_json(manifest_path, manifest)
    print(json.dumps({"status": "ready", **counts, "sandbox_csv_count": manifest["sandbox_csv_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
