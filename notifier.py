from github import Github


def create_issue(repo_name, token, entry, summary):
    g = Github(token)
    repo = g.get_repo(repo_name)
    arxiv_id = entry.id.split("/")[-1]
    companies = ", ".join(entry.companies)
    year = entry.published[:4]
    title = entry.title

    labels = [year] + entry.companies
    issue_title = f"[arXiv {year}] {title} ({companies})"
    body = f"""🧠 **Title:** {title}

📅 **Published:** {entry.published}
🔗 **URL:** {entry.link}
🧑‍💼 **Companies:** {companies}

📝 **Summary:**  
{summary}
"""
    repo.create_issue(title=issue_title, body=body, labels=labels[:5])
