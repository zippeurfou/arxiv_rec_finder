# notifier.py
import hashlib

from github import Github, GithubException


def _color_for_label(name: str) -> str:
    """
    Deterministically turn `name` into a “nice” 6‑digit hex string.
    We:
      1. Compute MD5(name.encode("utf8"))
      2. Take the first 3 bytes → R, G, B
      3. Clamp each channel to [0x40, 0xE0] so it’s neither too dark nor too light.
    """
    digest = hashlib.md5(name.encode("utf8")).digest()
    rgb = []
    for b in digest[:3]:
        # clamp to range [0x40, 0xE0] to avoid extremes
        clamped = 0x40 + (b % (0xE0 - 0x40))
        rgb.append(clamped)
    return "{:02x}{:02x}{:02x}".format(*rgb)


def _ensure_label(repo, label_name: str) -> None:
    """
    If a label with `label_name` doesn’t exist in `repo`, create it using a
    deterministic color from `_color_for_label(label_name)`. If it does exist,
    do nothing (we don’t touch its existing color).
    """
    try:
        repo.get_label(label_name)
    except GithubException as e:
        if e.status == 404:
            color = _color_for_label(label_name)
            repo.create_label(name=label_name, color=color)
        else:
            raise


def _labels(year: str, companies) -> list[str]:
    """Build the label list from year + companies, dropping empty/falsy names.

    GitHub rejects empty label names (422), so an empty `year` (e.g. when
    `entry.published` is missing) or any blank company must be filtered out.
    """
    return [lbl for lbl in ([year] + list(companies or [])) if lbl]


def create_issue(repo_name: str, token: str, entry, summary: str):
    """
    Create a GitHub issue for the given arXiv entry with the provided summary.
    The issue will be labeled with the year of publication and the companies.
    Args:
        repo_name (str): The name of the GitHub repository (e.g., "username/repo").
        token (str): GitHub personal access token with permissions to create issues.
        entry: An arXiv entry object containing metadata like title, published date, link, etc.
        summary (str): A summary of the paper.
    Returns:
        None
    """
    g = Github(token)
    repo = g.get_repo(repo_name)

    # Build “year” and each company label
    year = entry.published[:4]
    companies = entry.companies or []
    labels = _labels(year, companies)

    # 1) ensure each label exists (with a nice color)
    for lbl in labels:
        _ensure_label(repo, lbl)

    # 2) construct issue text as before
    title = entry.title
    company_list = ", ".join(companies)
    issue_title = f"[arXiv {year}] {title} ({company_list})"
    body = f"""🧠 **Title:** {title}

📅 **Published:** {entry.published}
🔗 **URL:** {entry.link}
🧑‍💼 **Companies:** {company_list}

📝 **Summary:**  
{summary}
"""
    # Now all labels definitely exist, so we can safely pass their names
    repo.create_issue(title=issue_title, body=body, labels=labels[:5])
