import feedparser

def get_recent_arxiv_papers(query, category, max_results=100):
    base_url = "http://export.arxiv.org/api/query?"
    q = f"search_query=all:{query}+AND+cat:{category}&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    feed = feedparser.parse(base_url + q)
    return feed.entries

