import logging
import os
from datetime import date
from urllib.parse import urlparse

import yaml
from tqdm import tqdm

from arxiv_client import get_recent_arxiv_papers
from arxiv_parser import extract_emails_from_arxiv_pdf
from cache import append_record, load_cache
from filter_affiliations import (
    decide_companies,
    extract_affiliations,
    get_signals_cached,
)
from kb.ids import extract_arxiv_id
from notifier import create_issue
from store import load_seen_from_issues
from substack_client import fetch_substack_posts, get_substack_domains
from summarizer import summarize_with_ollama

logging.basicConfig(level=logging.INFO)

CACHE_PATH = "state/email_cache.jsonl"


class FakeEntry:
    def __init__(self, id="", title="", published="", link="", companies=None):
        self.id = id
        self.title = title
        self.published = published
        self.link = link
        self.companies = companies


def load_config(path="config.yaml"):
    """Load YAML configuration from disk."""
    with open(path) as f:
        return yaml.safe_load(f)


def collect_new_arxiv_entries(config, seen_ids):
    """
    Fetch recent arXiv entries for each category, filter out ones in `seen_ids`,
    and return a list of new entries.
    """
    tech_query = config["search_query"]
    categories = [c.strip() for c in config["arxiv_category"].split("OR")]
    new_entries = []
    seen_local = set()

    for cat in categories:
        recent = get_recent_arxiv_papers(tech_query, cat)
        for entry in tqdm(
            recent,
            desc=f"Fetching arXiv ({cat})",
            unit="paper",
            leave=False,
        ):
            if entry.id in seen_ids:
                continue
            if entry.id not in seen_local:
                new_entries.append(entry)
                seen_local.add(entry.id)

    return new_entries


def process_entries(
    entries, tech_domains, cache, seen_ids, repo, token, cache_path, download=True
):
    """
    Decide each entry using cached signals (downloading + caching if missing),
    then file GitHub issues for matches that haven't been seen yet.

    For every entry:
      - skip if its link is already in `seen_ids`
      - normalize to an arXiv id and get signals from the cache (or download the
        PDF via `extract_emails_from_arxiv_pdf` unless `download=False`)
      - on a cache miss while downloading, build + store a cache record and
        checkpoint it to `cache_path` (if provided)
      - decide companies from the signals; if matched and not already seen,
        set `entry.companies`, summarize, create an issue, and mark it seen.
    """
    pdf_fn = extract_emails_from_arxiv_pdf if download else (lambda _i: [])

    for entry in tqdm(
        entries,
        desc="Processing new arXiv papers",
        unit="paper",
        leave=False,
    ):
        if entry.link in seen_ids:
            continue

        aid = extract_arxiv_id(entry.id) or entry.id
        # extract_affiliations() calls entry.get("authors", []); guard plain
        # objects that lack .get so a new paper's affiliation metadata is still
        # honored (parity with the old has_big_tech_author pass-1).
        try:
            affs = list(extract_affiliations(entry))
        except Exception:
            affs = []
        sig = get_signals_cached(aid, cache, pdf_fn, affiliations=affs)

        if aid not in cache and download:
            rec = {
                "arxiv_id": aid,
                "title": entry.title,
                "published": entry.published,
                "url": entry.link,
                "affiliations": sig["affiliations"],
                "emails": sig["emails"],
                "checked": date.today().isoformat(),
            }
            cache[aid] = rec
            if cache_path:
                append_record(cache_path, rec)

        companies = decide_companies(sig["affiliations"], sig["emails"], tech_domains)
        if companies and entry.link not in seen_ids:
            entry.companies = companies
            summary = summarize_with_ollama(entry.title, getattr(entry, "summary", ""))
            create_issue(repo, token, entry, summary)
            seen_ids.add(entry.link)
            logging.info(f"✅ Issue for arXiv paper: {entry.title}")


def redecide_cache(cache, tech_domains, seen_ids, repo, token):
    """
    Retroactively file issues for cached papers that now match current domains.

    Re-decides every cached record against `tech_domains` (no re-download). For
    matches whose URL hasn't been seen, builds a FakeEntry from cached metadata,
    summarizes, files an issue, and marks the URL seen.
    """
    for aid, rec in tqdm(
        cache.items(),
        desc="Re-deciding cache",
        unit="paper",
        leave=False,
    ):
        url = rec.get("url")
        if not url or url in seen_ids:
            continue
        companies = decide_companies(
            rec.get("affiliations", []), rec.get("emails", []), tech_domains
        )
        if companies:
            try:
                fe = FakeEntry(
                    id=url,
                    title=rec.get("title", aid),
                    published=rec.get("published", ""),
                    link=url,
                    companies=companies,
                )
                summary = summarize_with_ollama(fe.title, "")
                create_issue(repo, token, fe, summary)
                seen_ids.add(url)
                logging.info(f"✅ Retroactive issue for cached paper: {fe.title}")
            except Exception as e:
                logging.warning(f"failed to file retroactive issue for {aid}: {e}")
                continue


def process_substack_users(config, seen_ids, repo, token):
    """
    For each Substack username, fetch their domains, then for each post:
      - Skip if already in seen_ids
      - Otherwise summarize + create a FakeEntry + create an issue
    """
    usernames = config.get("substack_username", [])
    limit = config.get("substack_limit", 5)

    with tqdm(
        total=len(usernames),
        desc="Processing Substack users",
        unit="user",
        leave=False,
    ) as user_bar:
        for username in usernames:
            domains = get_substack_domains(username)
            for domain_url in domains:
                posts = fetch_substack_posts(domain_url, limit=limit)

                for post in tqdm(
                    posts,
                    desc=f"  Posts for {domain_url}",
                    unit="post",
                    leave=False,
                ):
                    post_url = post["url"].rstrip("/")
                    if post_url in seen_ids:
                        continue

                    summary = summarize_with_ollama(post["title"], post["content"])
                    fe = FakeEntry(
                        id=post_url,
                        title=post["title"],
                        published=post["date"],
                        link=post_url,
                        companies=[
                            "Substack",
                            urlparse(post_url).hostname.split(".")[0].capitalize(),
                        ],
                    )
                    create_issue(repo, token, fe, summary)
                    logging.info(f"✅ Created Substack issue: {post['title']}")

            user_bar.update(1)


def main():
    # 0) Load config + token + repo name
    config = load_config("config.yaml")
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    repo = config["github"]["repo"]

    # 1) Fetch all already-seen URLs from GitHub issues
    seen_ids = load_seen_from_issues(repo, token)

    # 2) Load the persisted extraction cache (arxiv_id -> signals + metadata)
    cache = load_cache(CACHE_PATH)

    # 3) Collect new arXiv entries (skip ones already in seen_ids)
    new = collect_new_arxiv_entries(config, seen_ids)

    # 4) Decide + file issues for new entries, caching downloaded signals
    process_entries(
        new, config["tech_domains"], cache, seen_ids, repo, token, CACHE_PATH
    )

    # 5) Retroactively re-decide the whole cache against current domains
    redecide_cache(cache, config["tech_domains"], seen_ids, repo, token)

    # 6) Process Substack posts
    process_substack_users(config, seen_ids, repo, token)


if __name__ == "__main__":
    main()
