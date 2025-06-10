import logging
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import yaml
from tqdm import tqdm

from arxiv_client import get_recent_arxiv_papers
from filter_affiliations import has_big_tech_author
from notifier import create_issue
from store import load_seen_from_issues
from substack_client import fetch_substack_posts, get_substack_domains
from summarizer import summarize_with_ollama

logging.basicConfig(level=logging.INFO)


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


def submit_arxiv_issues(entries, config, seen_ids, repo, token):
    """
    Check affiliations for entries in parallel, then for those with big-tech
    authors, summarize sequentially and create issues.
    """
    tech_domains = config["tech_domains"]

    entries_to_check = [entry for entry in entries if entry.id not in seen_ids]
    valid_entries = []

    with ThreadPoolExecutor() as executor:
        # Submit all tasks
        tasks = [
            (entry, executor.submit(has_big_tech_author, entry, tech_domains))
            for entry in entries_to_check
        ]

        # Collect results
        for entry, future in tqdm(
            tasks,
            desc="Checking affiliations",
            unit="paper",
            leave=False,
        ):
            try:
                if future.result():
                    valid_entries.append(entry)
            except Exception as e:
                logging.warning(f"Error checking affiliation for {entry.id}: {e}")

    for entry in tqdm(
        valid_entries,
        desc="Processing new arXiv papers",
        unit="paper",
        leave=False,
    ):
        if entry.id in seen_ids:
            continue

        # Summarize with Ollama sequentially given Ollama is ressource-intensive
        # TODO: Consider not using an LLM to make this faster but it is too fun to do it on a github workflow :D
        summary = summarize_with_ollama(entry.title, entry.summary)
        create_issue(repo, token, entry, summary)
        logging.info(f"✅ Issue for arXiv paper: {entry.title}")


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
                    desc=f"  Posts for {username}",
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

    # 2) Collect new arXiv entries (skip ones already in seen_ids)
    new_arxiv = collect_new_arxiv_entries(config, seen_ids)

    # 3) Submit issues for eligible arXiv papers
    submit_arxiv_issues(new_arxiv, config, seen_ids, repo, token)

    # 4) Process Substack posts
    process_substack_users(config, seen_ids, repo, token)


if __name__ == "__main__":
    main()
