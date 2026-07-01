import re
from dataclasses import dataclass

from kb.ids import extract_arxiv_id

_PREAMBLE = re.compile(
    r"^\s*(?:sure[!,.\s]*|okay[!,.\s]*|of course[!,.\s]*)?"
    r"here(?:'s| is)\s+(?:a|the)\b[^\n.]*?summ[a-z]*[^\n.:]*:\s*\n?",
    re.IGNORECASE,
)

_SUMMARY = re.compile(r"\*\*Summary:?\*\*:?\s*(.*)", re.DOTALL | re.IGNORECASE)

# Issue titles are built by notifier.py as "[arXiv <year>] <title> (<companies>)".
# Strip that decoration to recover the clean paper title.
_TITLE_PREFIX = re.compile(r"^\[arxiv\s+\d{4}\]\s*", re.IGNORECASE)
_TITLE_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def _clean_title(raw_title: str) -> str:
    t = _TITLE_PREFIX.sub("", raw_title.strip())
    t = _TITLE_SUFFIX.sub("", t)
    return t.strip()


@dataclass
class PaperRecord:
    arxiv_id: str
    title: str
    year: int | None
    companies: list[str]
    url: str
    issue: int
    summary: str


def _clean_summary(body: str) -> str:
    m = _SUMMARY.search(body)
    text = (m.group(1) if m else body).strip()
    return _PREAMBLE.sub("", text, count=1).strip()


def parse_issue(
    number: int, title: str, body: str, labels: list[str]
) -> PaperRecord | None:
    arxiv_id = extract_arxiv_id(body)
    if not arxiv_id:
        return None
    years = [int(label) for label in labels if label.isdigit() and len(label) == 4]
    companies = [label for label in labels if not (label.isdigit() and len(label) == 4)]
    url_m = re.search(r"(https?://arxiv\.org/\S+)", body)
    return PaperRecord(
        arxiv_id=arxiv_id,
        title=_clean_title(title),
        year=years[0] if years else None,
        companies=companies,
        url=url_m.group(1) if url_m else f"https://arxiv.org/abs/{arxiv_id}",
        issue=number,
        summary=_clean_summary(body),
    )


def iter_issues(repo_name: str, token: str, since_issue: int = 0):
    """Yield PaperRecord for all issues with number > since_issue. Uses PyGithub."""
    from github import Github

    repo = Github(token).get_repo(repo_name)
    for issue in repo.get_issues(state="all"):
        if issue.number <= since_issue:
            continue
        rec = parse_issue(
            issue.number,
            issue.title,
            issue.body or "",
            [label.name for label in issue.labels],
        )
        if rec:
            yield rec
