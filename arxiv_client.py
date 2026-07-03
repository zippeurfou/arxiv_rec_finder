import logging
import threading
import time
from urllib.parse import quote_plus

import feedparser
import requests

USER_AGENT = "arxiv-rec-finder/0.1 (+https://github.com/zippeurfou/arxiv_rec_finder)"
MIN_INTERVAL_SEC = 3.0  # arXiv TOU: <= 1 request / 3s to the API
REQUEST_TIMEOUT = 30
MAX_RETRIES = 5
BASE_URL = "http://export.arxiv.org/api/query?"

_pace_lock = threading.Lock()
_last_request_ts = 0.0


def _reset_pacing_for_tests():
    global _last_request_ts
    _last_request_ts = 0.0


def _is_rate_limited_body(content: bytes) -> bool:
    head = (content or b"")[:64].strip().lower()
    return head.startswith(b"rate exceeded")


def _paced_get(url: str) -> bytes:
    """GET with >=MIN_INTERVAL_SEC spacing, timeout, and retry/backoff on
    429/503 and arXiv's HTTP-200 'Rate exceeded.' soft-throttle."""
    global _last_request_ts
    for attempt in range(MAX_RETRIES):
        with _pace_lock:
            wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_request_ts)
            if wait > 0:
                time.sleep(wait)
            _last_request_ts = time.monotonic()
        try:
            resp = requests.get(
                url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
            )
        except requests.RequestException as e:
            logging.warning(f"arXiv GET error (attempt {attempt + 1}): {e}")
            time.sleep((attempt + 1) * MIN_INTERVAL_SEC)
            continue

        if resp.status_code == 200 and not _is_rate_limited_body(resp.content):
            return resp.content
        if resp.status_code == 200:  # soft rate-limit body
            logging.warning("arXiv soft rate-limit ('Rate exceeded.'); backing off")
        elif resp.status_code in (429, 500, 502, 503, 504):
            logging.warning(f"arXiv HTTP {resp.status_code}; backing off")
        else:
            resp.raise_for_status()
        retry_after = int(resp.headers.get("Retry-After", 0) or 0)
        time.sleep(max(retry_after, (attempt + 1) * MIN_INTERVAL_SEC))
    raise RuntimeError(f"arXiv API failed after {MAX_RETRIES} retries: {url}")


def _build_query(query, category, start, max_results, since=None, until=None):
    parts = [f"all:{quote_plus(query)}", f"cat:{quote_plus(category)}"]
    if since or until:
        lo = since or "197001010000"
        hi = until or "299912312359"
        parts.append(f"submittedDate:[{lo}+TO+{hi}]")
    search = "+AND+".join(parts)
    return (
        f"search_query={search}"
        f"&start={start}&max_results={max_results}"
        "&sortBy=submittedDate&sortOrder=descending"
    )


def get_recent_arxiv_papers(query, category, max_results=400):
    url = BASE_URL + _build_query(query, category, 0, max_results)
    return feedparser.parse(_paced_get(url)).entries
