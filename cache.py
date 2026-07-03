import json
import logging
from pathlib import Path


def load_cache(path) -> dict:
    """Load state/email_cache.jsonl into {arxiv_id: record}. Later lines win.
    Malformed lines are skipped with a warning."""
    path = Path(path)
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            out[rec["arxiv_id"]] = rec
        except (json.JSONDecodeError, KeyError) as e:
            logging.warning(f"skipping malformed cache line: {e}")
    return out


def append_record(path, record: dict) -> None:
    """Append one record (checkpoint). load_cache() dedups (last wins)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def compact(path) -> None:
    """Rewrite the file with one line per arxiv_id (drops superseded lines)."""
    path = Path(path)
    data = load_cache(path)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for rec in data.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(path)
