from github import Github
import re

def load_seen_from_issues(repo_name, token):
    """
    Fetch all issues (open + closed) in `repo_name` and collect every URL found
    in the issue body. Return a set of those URLs, which will be used by main.py
    to avoid re‐posting the same arXiv entry or Substack post.
    """
    g = Github(token)
    repo = g.get_repo(repo_name)
    seen = set()

    url_pattern = re.compile(r"https?://\S+")

    for issue in repo.get_issues(state="all"):
        body = issue.body or ""
        for line in body.splitlines():
            for match in url_pattern.findall(line):
                # Store the raw URL (e.g. "https://arxiv.org/abs/2505.15091v3" or "https://some.substack.com/slug")
                seen.add(match.rstrip())
    return seen
