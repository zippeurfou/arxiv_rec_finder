# main.py
import logging
import os
from urllib.parse import urlparse

import yaml

from arxiv_client import get_recent_arxiv_papers
from filter_affiliations import has_big_tech_author
from notifier import create_issue
from store import load_seen_from_issues
from substack_client import fetch_substack_posts, get_substack_domains
from summarizer import summarize_with_ollama

logging.basicConfig(level=logging.INFO)


class FakeEntry:
    def __init__(
        self,
        id="",
        title="",
        published="",
        link="",
        companies=None,
    ):
        self.id = id
        self.title = title
        self.published = published
        self.link = link
        self.companies = companies


def main():
    config = yaml.safe_load(open("config.yaml"))
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    repo = config["github"]["repo"]

    seen = load_seen_from_issues(repo, token)

    # 1) Process arXiv papers
    cats = [c.strip() for c in config["arxiv_category"].split("OR")]
    papers, seen_arxiv_ids = [], set()

    for cat in cats:
        for entry in get_recent_arxiv_papers(config["search_query"], cat):
            # entry.id is something like "http://arxiv.org/abs/2505.15091v3"
            if entry.id in seen:
                continue

            if entry.id not in seen_arxiv_ids:
                papers.append(entry)
                seen_arxiv_ids.add(entry.id)

    for entry in papers:
        # Skip again if somehow already in seen (redundant guard)
        if entry.id in seen:
            continue

        if has_big_tech_author(entry, config["tech_domains"]):
            summary = summarize_with_ollama(entry.title, entry.summary)
            create_issue(repo, token, entry, summary)
            logging.info(f"✅ Issue for arXiv paper: {entry.title}")

    # 2) Process Substack posts
    for username in config.get("substack_username", []):
        urls = get_substack_domains(username)
        for url in urls:
            posts = fetch_substack_posts(url, limit=config.get("substack_limit", 5))
            for post in posts:
                post_url = post["url"].rstrip("/")
                if post_url in seen:
                    continue

                # Create a fake entry for Substack
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


if __name__ == "__main__":
    main()
