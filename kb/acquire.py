# kb/acquire.py
from pathlib import Path
import time
import requests

ARXIV2MD_API = "https://arxiv2md.org/api/markdown"


def _default_fetcher(arxiv_id: str) -> str:
    """Fetch clean markdown incl. references via the hosted arxiv2md.org API."""
    time.sleep(3)  # politeness / rate limiting for bulk backfill
    resp = requests.get(
        ARXIV2MD_API,
        params={"url": arxiv_id, "remove_refs": "false"},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.text


def get_fulltext(arxiv_id: str, cache_dir: Path, fetcher=_default_fetcher) -> str:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{arxiv_id}.md"
    if cached.exists():
        return cached.read_text()
    md = fetcher(arxiv_id)
    cached.write_text(md)
    return md
