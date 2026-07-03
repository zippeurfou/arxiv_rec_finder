import argparse
import logging
import os
from datetime import date

import feedparser
import yaml

import arxiv_client as ac
from arxiv_parser import extract_emails_from_arxiv_pdf
from cache import append_record, load_cache
from filter_affiliations import decide_companies, extract_affiliations
from kb.ids import extract_arxiv_id
from main import CACHE_PATH, FakeEntry
from notifier import create_issue
from store import load_seen_from_issues
from summarizer import summarize_with_ollama

logging.basicConfig(level=logging.INFO)


def _to_stamp(d, end=False):
    """Convert a YYYY-MM-DD date string to an arXiv submittedDate stamp.

    ``YYYYMMDD`` + ``0000`` (start of day) or ``2359`` (end of day, when
    ``end=True``).
    """
    y, m, day = d.split("-")
    return f"{y}{m}{day}{'2359' if end else '0000'}"


def _fetch_page(query, category, start, page_size, since, until):
    """Fetch one page of arXiv results and return its ``feedparser`` entries.

    Kept as a thin, side-effect-only-at-call-time function so tests can
    monkeypatch ``backfill._fetch_page`` without touching the network.
    """
    url = ac.BASE_URL + ac._build_query(query, category, start, page_size, since, until)
    return feedparser.parse(ac._paced_get(url)).entries


def iter_all(query, category, since, until=None, page_size=1000):
    """Yield all entries across pages, stopping when a page returns empty."""
    start = 0
    while True:
        entries = _fetch_page(query, category, start, page_size, since, until)
        if not entries:
            return
        yield from entries
        start += page_size


def run(since, until=None, max_workers=6):
    """Backfill the extraction cache + file issues over a submittedDate window.

    Serial by design: the paced arXiv client already serializes API calls and
    ``cache.append_record`` is not thread-safe, so we do not parallelize PDF
    downloads in this phase. ``max_workers`` is accepted for forward-compat /
    CLI parity but is currently unused.
    """
    _ = max_workers  # accepted-but-unused (see docstring); forward-compat only

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    token = os.environ["GITHUB_TOKEN"]
    repo = cfg["github"]["repo"]
    domains = cfg["tech_domains"]
    query = cfg["search_query"]
    cats = [c.strip() for c in cfg["arxiv_category"].split("OR")]

    cache = load_cache(CACHE_PATH)
    seen = load_seen_from_issues(repo, token)
    lo = _to_stamp(since)
    hi = _to_stamp(until, end=True) if until else None

    for cat in cats:
        for entry in iter_all(query, cat, lo, hi):
            aid = extract_arxiv_id(entry.id) or entry.id
            if aid in cache:
                rec = cache[aid]
            else:
                try:
                    emails = extract_emails_from_arxiv_pdf(entry.id.rsplit("/", 1)[-1])
                except Exception as e:
                    logging.warning(f"{aid}: {e}")
                    emails = []
                # Parity with the Phase-5 daily path: populate affiliations from
                # the author metadata so backfill records have identical shape
                # and signals to daily records.
                try:
                    affs = list(extract_affiliations(entry))
                except Exception:
                    affs = []
                rec = {
                    "arxiv_id": aid,
                    "title": entry.title,
                    "published": entry.published,
                    "url": entry.link,
                    "affiliations": affs,
                    "emails": emails,
                    "checked": date.today().isoformat(),
                }
                cache[aid] = rec
                append_record(CACHE_PATH, rec)  # checkpoint every paper

            companies = decide_companies(rec["affiliations"], rec["emails"], domains)
            if companies and rec["url"] not in seen:
                fe = FakeEntry(
                    id=rec["url"],
                    title=rec["title"],
                    published=rec["published"],
                    link=rec["url"],
                    companies=companies,
                )
                create_issue(repo, token, fe, summarize_with_ollama(fe.title, ""))
                seen.add(rec["url"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--since", required=True, help="YYYY-MM-DD")
    p.add_argument("--until", default=None, help="YYYY-MM-DD")
    p.add_argument("--max-workers", type=int, default=6)
    a = p.parse_args()
    run(a.since, a.until, a.max_workers)
