from github import Github


def load_seen_from_issues(repo_name, token):
    g = Github(token)
    repo = g.get_repo(repo_name)
    seen = set()
    for issue in repo.get_issues(state="all"):
        if "https://arxiv.org/abs/" in issue.body:
            for line in issue.body.splitlines():
                if "https://arxiv.org/abs/" in line:
                    seen.add(line.strip().split("/")[-1])
    return seen
