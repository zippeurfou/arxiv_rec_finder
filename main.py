import logging
import os

import yaml

from arxiv_client import get_recent_arxiv_papers
from filter_affiliations import has_big_tech_author
from notifier import create_issue
from store import load_seen_from_issues
from summarizer import summarize_with_ollama

logging.basicConfig(level=logging.INFO)


def main():
    config = yaml.safe_load(open("config.yaml"))
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    repo = config["github"]["repo"]

    seen = load_seen_from_issues(repo, token)

    cats = [c.strip() for c in config["arxiv_category"].split("OR")]
    papers, ids = [], set()
    for cat in cats:
        for entry in get_recent_arxiv_papers(config["search_query"], cat):
            aid = entry.id.split("/")[-1]
            if aid not in ids:
                papers.append(entry)
                ids.add(aid)

    for entry in papers:
        aid = entry.id.split("/")[-1]
        if aid in seen:
            continue
        if has_big_tech_author(entry, config["tech_domains"]):
            summary = summarize_with_ollama(entry.title, entry.summary)
            create_issue(repo, token, entry, summary)
            logging.info(f"✅ Issue for {entry.title}")


if __name__ == "__main__":
    main()
