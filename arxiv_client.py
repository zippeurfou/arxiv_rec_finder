from urllib.parse import quote_plus

import feedparser


def get_recent_arxiv_papers(query, category, max_results=100):
    base_url = "http://export.arxiv.org/api/query?"
    safe_query = quote_plus(query)  # encode "a b" → "a+b"
    safe_cat = quote_plus(category)
    q = (
        f"search_query=all:{safe_query}"
        f"+AND+cat:{safe_cat}"
        "&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={max_results}"
    )
    feed = feedparser.parse(base_url + q)
    return feed.entries
