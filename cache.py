import json
import logging
import os
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
    """Append one record (checkpoint). load_cache() dedups (last wins).

    NOT thread-safe: concurrent appends from multiple threads or processes
    must be serialized by the caller with an external lock (Phase 6 backfill
    may parallelize PDF work). The flush + os.fsync make each append
    crash-durable, so a mid-backfill crash won't lose the checkpoint.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def compact(path) -> None:
    """Rewrite the file with one line per arxiv_id (drops superseded lines).

    Records are written sorted by arxiv_id for a stable, review-friendly diff.

    The caller MUST ensure no concurrent append_record is running: compact
    reads the whole file then atomically replaces it, so any appends landing
    in between would be lost.
    """
    path = Path(path)
    data = load_cache(path)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for rec in sorted(data.values(), key=lambda r: r["arxiv_id"]):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(path)
