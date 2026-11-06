"""Only public task text is available to the workflow. Scoring is a separate CLI."""
from lab.common import DATA, VENDOR, read_json


def load_tasks(split="easy"):
    if split not in {"easy", "medium", "human"}:
        raise ValueError("split must be easy, medium or human")
    path = DATA / "public" / f"{split}.json"
    if not path.exists():
        raise RuntimeError("Run python scripts/bootstrap.py first")
    return read_json(path)


def select_tasks(split="easy", limit=1, uid=None, subset="dev"):
    tasks = load_tasks(split)
    if uid:
        selected = [task for task in tasks if task["uid"] == uid]
        if not selected:
            raise ValueError(f"Unknown UID: {uid}")
        return selected
    if subset != "all":
        if split != "easy":
            raise ValueError("Local dev/holdout IDs belong to easy; use --subset all for other splits")
        ids = set(read_json(DATA / "splits.json")[subset])
        tasks = [task for task in tasks if task["uid"] in ids]
    if limit < 1:
        raise ValueError("--limit must be positive")
    return tasks[:limit]


def output_schema():
    return read_json(VENDOR / "chinatravel" / "evaluation" / "output_schema.json")
