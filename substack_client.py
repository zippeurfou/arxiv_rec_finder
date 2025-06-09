import logging

from substack_api import Newsletter, User


def get_substack_domains(username):
    try:
        user = User(username)
        newsletters = user.get_subscriptions()
        return [f"https://{n.get('domain')}" for n in newsletters]
    except Exception as e:
        logging.warning(f"Substack domain fetch failed: {e}")
        return []


def fetch_substack_posts(url, limit=3):
    try:
        nl = Newsletter(url)
        posts = nl.get_posts(limit=limit)
        result = []
        for p in posts:
            meta = p.get_metadata()
            result.append(
                {
                    "title": meta.get("title", ""),
                    "date": meta.get("post_date"),
                    "url": meta.get("canonical_url"),
                    "content": p.get_content(),
                }
            )
        return result
    except Exception as e:
        logging.warning(f"Substack fetch failed: {e}")
        return []
