import datetime
import logging

import feedparser
import requests
import cloudscraper

_SCRAPER = cloudscraper.create_scraper(
    browser={
        'custom': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/137.0.0.0 Safari/537.36'
    }
)


def get_substack_domains(username):
    """
    Manually hit Substack’s “public_profile” JSON endpoint with a fake User-Agent
    so that we’re not blocked. Returns a list of “https://<domain>” strings.
    """
    url = f"https://substack.com/api/v1/user/{username}/public_profile"
    headers = {
        # Any realistic UA will generally work—this one mimics Chrome on macOS
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        # “subscriptions” is a list of dicts; each dict has a “domain” key
        domains = [
            f"https://{sub['publication']['subdomain']}.substack.com"
            for sub in data.get("subscriptions", [])
        ]
        return domains
    except requests.exceptions.HTTPError as e:
        logging.warning(f"Substack domain fetch failed: {e!r}")
        # For now hard coding it, as I am getting blocked by Substack for the Github Action.
        # This is a workaround until I find a better way to fetch Substack domains.
        # I am suspecting that Substack is blocking the IP of the Github Action runner.
        # TODO: Find a better way to fetch Substack domains.
        return [
            "https://recsysml.substack.com",
            "https://happystrongcoder.substack.com",
            "https://datamachina.substack.com",
            "https://stkbailey.substack.com",
            "https://dhruvil.substack.com",
            "https://dblalock.substack.com",
            "https://cameronrwolfe.substack.com",
            "https://mikkeldengsoe.substack.com",
            "https://lukezhuo.substack.com",
            "https://mlfrontiers.substack.com",
            "https://vicki.substack.com",
            "https://on.substack.com",
            "https://aakashgupta.substack.com",
            "https://quastor.substack.com",
            "https://erishabh.substack.com",
            "https://recsys.substack.com",
            "https://roizner.substack.com",
        ]

    except Exception as e:
        logging.warning(f"Unexpected error fetching Substack domains: {e!r}")
        return []


# def get_substack_domains(username):
#     try:
#         user = User(username)
#         newsletters = user.get_subscriptions()
#         return [f"https://{n.get('domain')}" for n in newsletters]
#     except Exception as e:
#         logging.warning(f"Substack domain fetch failed: {e}")
#         return []


# def fetch_substack_posts(url, limit=3):
#     try:
#         nl = Newsletter(url)
#         posts = nl.get_posts(limit=limit)
#         result = []
#         for p in posts:
#             meta = p.get_metadata()
#             result.append(
#                 {
#                     "title": meta.get("title", ""),
#                     "date": meta.get("post_date"),
#                     "url": meta.get("canonical_url"),
#                     "content": p.get_content(),
#                 }
#             )
#         return result
#     except Exception as e:
#         logging.warning(f"Substack fetch failed: {e}")
#         return []


def _format_date(entry):
    """
    Extract and format the published/updated date from a feed entry as an ISO string
    that starts with the year, e.g., '2025-06-05T14:30:25Z'.
    Falls back to the raw string if parsing fails.
    """
    dt = None
    # feedparser provides structured time tuples
    if getattr(entry, "published_parsed", None):
        dt = datetime.datetime(
            *entry.published_parsed[:6], tzinfo=datetime.timezone.utc
        )
    elif getattr(entry, "updated_parsed", None):
        dt = datetime.datetime(*entry.updated_parsed[:6], tzinfo=datetime.timezone.utc)

    if dt:
        # Use ISO 8601 format without microseconds, with Z for UTC
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # Fallback to raw string
    return entry.get("published", entry.get("updated", ""))


def fetch_substack_posts(domain_url, limit=5):
    """
    Fetch the latest posts via the public RSS feed at /feed.
    Returns a list of dicts with keys: title, date, url, content.
    Dates are formatted as ISO strings starting with the year.
    """
    feed_url = f"{domain_url.rstrip('/')}/feed"
    logging.info(f"Feed URL: {feed_url}")
    try:
        feed = feedparser.parse(_SCRAPER.get(feed_url).text)
        if not feed.entries:
            logging.warning(f"Substack RSS feed empty or inaccessible: {feed_url}")
            logging.info(f"Feed content: {feed}")
            return []

        posts = []
        for entry in feed.entries[:limit]:
            # Format date
            date_str = _format_date(entry)
            # Some feeds use 'content', others use 'summary'
            raw_content = (
                entry.get("content", [{}])[0].get("value")
                if entry.get("content")
                else entry.get("summary", "")
            )
            posts.append(
                {
                    "title": entry.title,
                    "date": date_str,
                    "url": entry.link,
                    "content": raw_content,
                }
            )
        return posts

    except Exception as e:
        logging.warning(f"Substack fetch failed (RSS): {e}")
        logging.info(f"Feed content: {feed}")

        return []
