import logging

import requests
from substack_api import Newsletter


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
