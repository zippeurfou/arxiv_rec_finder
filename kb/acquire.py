# kb/acquire.py
import os
import time
from pathlib import Path

import requests

ARXIV2MD_API = "https://arxiv2md.org/api/markdown"


def _default_fetcher(arxiv_id: str) -> str:
    """Fetch clean markdown incl. references via the hosted arxiv2md.org API."""
    # Politeness / rate-limit delay; override via ARXIV2MD_SLEEP for bulk backfill.
    time.sleep(float(os.environ.get("ARXIV2MD_SLEEP", "3")))
    resp = requests.get(
        ARXIV2MD_API,
        params={"url": arxiv_id, "remove_refs": "false"},
        timeout=90,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def get_fulltext(arxiv_id: str, cache_dir: Path, fetcher=_default_fetcher) -> str:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{arxiv_id}.md"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    md = fetcher(arxiv_id)
    # Do not cache an empty/whitespace-only result: it would poison every
    # future run. Return it so the caller can decide; next run retries.
    if md.strip():
        cached.write_text(md, encoding="utf-8")
    return md
